from __future__ import annotations
import heapq,itertools,threading
from concurrent.futures import Future

class PriorityScheduler:
    def __init__(self,max_queue=32):
        self.max_queue=max_queue;self._q=[];self._cv=threading.Condition();self._counter=itertools.count();self._stop=False;self._t=threading.Thread(target=self._run,daemon=True,name='aux-inference-scheduler');self._t.start()
    def submit(self,priority:int,fn,*args,**kwargs):
        fut=Future()
        with self._cv:
            if len(self._q)>=self.max_queue: raise RuntimeError('inference_queue_full')
            heapq.heappush(self._q,(priority,next(self._counter),fut,fn,args,kwargs));self._cv.notify()
        return fut
    def _run(self):
        while True:
            with self._cv:
                while not self._q and not self._stop:self._cv.wait()
                if self._stop:return
                _,_,fut,fn,args,kwargs=heapq.heappop(self._q)
            if fut.set_running_or_notify_cancel():
                try:fut.set_result(fn(*args,**kwargs))
                except BaseException as e:fut.set_exception(e)
    def close(self):
        with self._cv:self._stop=True;self._cv.notify_all()
        self._t.join(timeout=2)
