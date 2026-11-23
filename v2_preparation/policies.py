"""Pure AWCT objective on exactly the existing BudgetSelect candidate pool."""
from sail.model import RepairDecision
from research_v2.policies import BudgetSelect


class PoolMinAWCT(BudgetSelect):
    def __call__(self,snapshot,context):
        self.original_decision=super().__call__(snapshot,context)
        self.original_selection=self.last_selected
        feasible=[c for c in self.last_candidates if c['quality_feasible']]
        chosen=min(feasible or self.last_candidates,key=lambda c:(c['awct'],c['churn'],c['name'],c['plan'].queues))
        self.last_selected=chosen
        return RepairDecision(context.Q,chosen['plan'])
