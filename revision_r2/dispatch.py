"""Dispatch-only sensitivity: planning and all pre-fault execution stay fixed."""
from sail.simulator import Simulator


class SkipUnready(Simulator):
    def __init__(self, *args, switch_time, **kwargs):
        super().__init__(*args, **kwargs)
        self.switch_time = switch_time
        self._push(switch_time, 4, 'switch', 'WAKE', None)

    def _settle(self):
        if self._now >= self.switch_time:
            for v in sorted(self._state): self._prepare(v)
            if not self._paused:
                for j, queue in enumerate(self._queues):
                    if not self._alive[j] or self._busy[j] is not None: continue
                    eligible = next((i for i, v in enumerate(queue) if self._state[v].status == 'PENDING'
                                     and self._state[v].input_status == 'READY'), None)
                    if eligible is not None and eligible > 0:
                        prefix = queue[:eligible]
                        task = queue.pop(eligible); queue.insert(0, task)
                        self._emit('QUEUE_SKIP', task, j, skipped=prefix)
        super()._settle()
