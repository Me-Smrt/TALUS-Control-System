#include <Arduino.h>
#include <Wire.h>
#include "board/pins.h"
#include "board/board_config.h"
#include "protocol/protocol.h"
#include "identity/persistent_config.h"
#include "can/can_driver.h"
#include "safety/safety_manager.h"
#include "servo/servo_manager.h"
#include "diagnostics/identify_button.h"
#include "diagnostics/status_led.h"

using namespace automaton;

identity::PersistentConfigStore config_store;
canbus::Mcp25625Driver can_driver;
safety::SafetyManager safety_manager;
servo::ServoManager servo_manager(Wire);
diagnostics::IdentifyButton identify_button;
diagnostics::StatusLed status_led;

static uint32_t active_session = 0;
static uint32_t last_status_ms = 0;
static uint32_t last_hello_attempt_ms = 0;
static uint32_t last_can_reinit_ms = 0;
static bool logic_power_ok = false;
static bool can_initialized = false;
static bool peripherals_initialized = false;
static bool identify_flash = false;

static bool readLogicPower() {
    const uint16_t raw = analogRead(pins::LOGIC_PWR_SENSE);
    if (logic_power_ok) return raw >= board::LOGIC_PWR_LOST_THRESHOLD;
    return raw >= board::LOGIC_PWR_PRESENT_THRESHOLD;
}

static protocol::Role storedRole() {
    return static_cast<protocol::Role>(config_store.current().role);
}

static safety::SafetyInputs collectSafetyInputs() {
    safety::SafetyInputs in;
    in.logic_power_ok = logic_power_ok;
    in.can_ok = can_initialized && can_driver.healthy();
    in.global_allow = logic_power_ok && (digitalRead(pins::GLOBAL_SERVO_ALLOW_OK) == HIGH);
    in.pca0_present = peripherals_initialized && servo_manager.pca0Present();
    in.pca1_present = peripherals_initialized && servo_manager.pca1Present();
    in.bank_pg[0] = logic_power_ok && digitalRead(pins::BANK_A_PG);
    in.bank_pg[1] = logic_power_ok && digitalRead(pins::BANK_B_PG);
    in.bank_pg[2] = logic_power_ok && digitalRead(pins::BANK_C_PG);
    in.bank_pg[3] = logic_power_ok && digitalRead(pins::BANK_D_PG);
    in.config_valid = storedRole() != protocol::Role::Unassigned;
    in.session_valid = active_session != 0;
    return in;
}

static void sendHello() {
    if (!can_driver.healthy()) return;
    protocol::Capabilities caps;
    caps.pwm_channel_count = board::PWM_CHANNEL_COUNT;
    caps.bank_count = board::BANK_COUNT;
    caps.supported_bank_mask = board::SUPPORTED_BANK_MASK;
    caps.feature_flags = 0x0001u; // normalized single-servo command supported
    can_driver.send(protocol::makeHelloUid(config_store.current().uid));
    can_driver.send(protocol::makeHelloMeta(storedRole(), 0));
    can_driver.send(protocol::makeHelloCaps(caps));
    can_driver.send(protocol::makeHelloState(safety_manager.state(), safety_manager.statusBits(), safety_manager.faults()));
}

static void handleServoCommand(const protocol::CanFrame& frame) {
    // [0]=protocol, [1..4]=session, [5]=channel, [6..7]=signed normalized goal [-1000,1000]
    if (!protocol::checkProtocol(frame)) return;
    const uint32_t session = protocol::read_u32(&frame.data[1]);
    if (session == 0 || session != active_session) return;
    if (!safety_manager.motionAuthorized()) return;
    const uint8_t channel = frame.data[5];
    const int16_t target = int16_t(protocol::read_u16(&frame.data[6]));
    servo_manager.commandNormalized(channel, target, true);
}

static void handleFrame(const protocol::CanFrame& frame, uint32_t now_ms) {
    const auto id = static_cast<protocol::CanId>(frame.id);
    switch (id) {
        case protocol::CanId::SessionBegin: {
            if (!protocol::checkProtocol(frame)) return;
            const uint32_t session = protocol::read_u32(&frame.data[1]);
            if (session == 0) return;
            servo_manager.disableAll();
            safety_manager.disarm(protocol::DisarmReason::NewSession);
            active_session = session;
            safety_manager.noteHeartbeat(now_ms);
            sendHello();
            break;
        }
        case protocol::CanId::Heartbeat: {
            if (!protocol::checkProtocol(frame)) return;
            const uint32_t session = protocol::read_u32(&frame.data[1]);
            if (session == active_session && session != 0) safety_manager.noteHeartbeat(now_ms);
            break;
        }
        case protocol::CanId::Disarm: {
            if (!protocol::checkProtocol(frame)) return;
            const uint32_t session = protocol::read_u32(&frame.data[2]);
            if (session == active_session || session == 0) {
                servo_manager.disableAll();
                safety_manager.disarm(protocol::DisarmReason::HostRequest);
            }
            break;
        }
        case protocol::CanId::ArmRequest: {
            if (!protocol::checkProtocol(frame)) return;
            const uint32_t session = protocol::read_u32(&frame.data[1]);
            const uint16_t seq = protocol::read_u16(&frame.data[5]);
            protocol::AckResult result = protocol::AckResult::SessionMismatch;
            if (session == active_session && session != 0) result = safety_manager.requestArm(now_ms);
            can_driver.send(protocol::makeArmAck(result, session, seq));
            break;
        }
        case protocol::CanId::SetRole: {
            if (!protocol::checkProtocol(frame)) return;
            const uint32_t session = protocol::read_u32(&frame.data[1]);
            const auto role = static_cast<protocol::Role>(frame.data[5]);
            const uint16_t seq = protocol::read_u16(&frame.data[6]);
            protocol::AckResult result = protocol::AckResult::SessionMismatch;
            if (session == active_session && session != 0 && !safety_manager.motionAuthorized()) {
                if (role == protocol::Role::Unassigned || uint8_t(role) <= uint8_t(protocol::Role::RightLeg) || role == protocol::Role::Custom) {
                    result = config_store.setRole(role) ? protocol::AckResult::Ok : protocol::AckResult::ConfigInvalid;
                } else result = protocol::AckResult::InvalidRole;
            }
            can_driver.send(protocol::makeConfigAck(result, session, seq));
            break;
        }
        case protocol::CanId::Ping: {
            if (!protocol::checkProtocol(frame)) return;
            const uint32_t session = protocol::read_u32(&frame.data[1]);
            const uint16_t nonce = protocol::read_u16(&frame.data[5]);
            can_driver.send(protocol::makePong(session, nonce, safety_manager.state()));
            break;
        }
        case protocol::CanId::ServoCommand:
            handleServoCommand(frame);
            break;
        default:
            break;
    }
}

static void enterUsbOnly() {
    active_session = 0;
    can_initialized = false;
    peripherals_initialized = false;
    safety_manager.disarm(protocol::DisarmReason::LogicPowerLost);
    safety_manager.setState(protocol::RcbState::UsbOnly);

    // External logic is unpowered in USB-only mode. Stop the peripheral controllers and
    // release every externally connected bus/control pin to avoid sourcing current through
    // protection diodes into MCP25625/PCA9685 circuitry.
    SPI.end();
    Wire.end();
    pinMode(pins::SPI_SCK_PIN, INPUT);
    pinMode(pins::SPI_MOSI_PIN, INPUT);
    pinMode(pins::SPI_MISO_PIN, INPUT);
    pinMode(pins::CAN_CS_N, INPUT);
    pinMode(pins::CAN_INT_N, INPUT);
    pinMode(pins::CAN_STBY, INPUT);
    pinMode(pins::I2C_SDA_PIN, INPUT);
    pinMode(pins::I2C_SCL_PIN, INPUT);
}

static void initializeExternalPeripherals() {
    safety_manager.setState(protocol::RcbState::Initializing);

    // Hardware OE is disabled because LOCAL_SERVO_ENABLE is still LOW. Initialize both
    // PCA9685s to full-off before CAN is allowed to accept any host motion command.
    // begin() reports whether both devices are present, but the individual probe
    // results remain useful for fault reporting.  Mark the peripheral layer initialized
    // even if one PCA is missing so we do not accidentally report both devices absent.
    servo_manager.begin();
    peripherals_initialized = true;

    can_initialized = can_driver.begin(board::CAN_BITRATE);
    if (!can_initialized) safety_manager.setFault(protocol::FAULT_CAN_CONTROLLER);
    else safety_manager.clearFault(protocol::FAULT_CAN_CONTROLLER);

    safety_manager.setState(protocol::RcbState::ReadyDisarmed);
    sendHello();
}

void setup() {
    // Safety output first. No other subsystem owns LOCAL_SERVO_ENABLE.
    safety_manager.begin();

    analogReadResolution(12);
    pinMode(pins::LOGIC_PWR_SENSE, INPUT);
    pinMode(pins::GLOBAL_SERVO_ALLOW_OK, INPUT);
    pinMode(pins::BANK_A_PG, INPUT); pinMode(pins::BANK_B_PG, INPUT);
    pinMode(pins::BANK_C_PG, INPUT); pinMode(pins::BANK_D_PG, INPUT);

    Serial.begin(115200);
    identify_button.begin();
    status_led.begin();
    config_store.begin();

    safety_manager.setState(protocol::RcbState::SafeBoot);
}

void loop() {
    const uint32_t now = millis();
    const bool new_logic_power = readLogicPower();

    if (!new_logic_power) {
        if (logic_power_ok) enterUsbOnly();
        logic_power_ok = false;
        safety_manager.disarm(protocol::DisarmReason::LogicPowerLost);
        safety_manager.setState(protocol::RcbState::UsbOnly);
        delay(10);
        return;
    }

    if (!logic_power_ok) {
        logic_power_ok = true;
        initializeExternalPeripherals();
    }

    can_driver.service(now);
    if (can_initialized && !can_driver.healthy()) {
        can_initialized = false;
        active_session = 0;
        servo_manager.disableAll();
        safety_manager.setFault(protocol::FAULT_CAN_CONTROLLER);
        safety_manager.disarm(protocol::DisarmReason::PeripheralLost);
        last_can_reinit_ms = now;
    }

    auto inputs = collectSafetyInputs();
    safety_manager.updateInputs(inputs);
    safety_manager.tick(now);

    protocol::CanFrame frame;
    while (can_driver.receive(frame)) handleFrame(frame, now);

    const auto button_event = identify_button.update(now);
    identify_flash = false;
    if (button_event == diagnostics::ButtonEvent::ShortPress) {
        identify_flash = true;
        if (can_driver.healthy()) can_driver.send(protocol::makeIdentify(config_store.current().uid));
    } else if (button_event == diagnostics::ButtonEvent::LongPress) {
        // Still conservative: long press never changes identity/role unless a future explicit
        // setup-mode gate is present, and it can never arm servo power.
        identify_flash = true;
    }

    if (can_driver.healthy() && uint32_t(now - last_status_ms) >= board::STATUS_INTERVAL_MS) {
        last_status_ms = now;
        can_driver.send(protocol::makeStatus(safety_manager.state(), storedRole(), safety_manager.statusBits(), safety_manager.faults()));
    }

    if (!can_driver.healthy() && uint32_t(now - last_can_reinit_ms) >= board::CAN_REINIT_INTERVAL_MS) {
        last_can_reinit_ms = now;
        safety_manager.disarm(protocol::DisarmReason::PeripheralLost);
        can_initialized = can_driver.begin(board::CAN_BITRATE);
        if (can_initialized) {
            safety_manager.clearFault(protocol::FAULT_CAN_CONTROLLER);
            active_session = 0; // reconnection always requires a new host session and explicit re-arm
            sendHello();
        }
    }

    if (can_driver.healthy() && uint32_t(now - last_hello_attempt_ms) >= board::HELLO_RETRY_MS && active_session == 0) {
        last_hello_attempt_ms = now;
        sendHello();
    }

    status_led.update(now, safety_manager.state(), safety_manager.faults(), identify_flash);
}
