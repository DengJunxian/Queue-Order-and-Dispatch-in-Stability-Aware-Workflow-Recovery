"""Assignment-preserving queue-order inversions with an explicit denominator."""
def inversion_count(sequence):
    # Count in O(n log n), independent of queue size; equal ranks are disallowed.
    values=list(sequence)
    if len(values)!=len(set(values)):raise ValueError('duplicate task rank')
    def split(a):
        if len(a)<2:return a,0
        left,x=split(a[:len(a)//2]);right,y=split(a[len(a)//2:]);i=j=0;out=[];n=x+y
        while i<len(left) and j<len(right):
            if left[i]<right[j]:out.append(left[i]);i+=1
            else:out.append(right[j]);j+=1;n+=len(left)-i
        return out+left[i:]+right[j:],n
    return split(values)[1]


def queue_disturbance(context,plan):
    original=dict(context.old_assignment);new=plan.assignment;eligible=context.Q-context.F
    inversions=pairs=retained=0
    for node,q in enumerate(context.original_queues):
        old=[v for v in q if v in eligible and new[v]==original[v]]
        rank={v:i for i,v in enumerate(old)};ordered=[rank[v] for v in plan.queues[node] if v in rank]
        assert len(ordered)==len(old)
        n=len(old);pairs+=n*(n-1)//2;retained+=n;inversions+=inversion_count(ordered)
    return {'queue_inversions':inversions,'comparable_pairs':pairs,'retained_tasks':retained,
            'order_disturbance':inversions/pairs if pairs else None}
