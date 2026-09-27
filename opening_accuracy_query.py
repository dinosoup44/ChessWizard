"""Frontend-neutral predicates for future Explorer opening filters."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class OpeningAccuracyQuery:
    accuracy_min: float | None = None
    accuracy_max: float | None = None
    adherence_min: float | None = None
    adherence_max: float | None = None
    variation_name: str = ''
    require_complete: bool = True
    user_deviation: bool | None = None
    deviation_loss_min_cp: int | None = None

    def __post_init__(self):
        if not isinstance(self.variation_name,str) or type(self.require_complete) is not bool: raise ValueError('Invalid variation/completeness filter.')
        for name in ('accuracy_min','accuracy_max','adherence_min','adherence_max'):
            value = getattr(self,name)
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= 100):
                raise ValueError('Accuracy/adherence bounds must be between 0 and 100.')
        for prefix in ('accuracy','adherence'):
            low, high = getattr(self,prefix+'_min'),getattr(self,prefix+'_max')
            if low is not None and high is not None and low > high: raise ValueError('Reversed metric bounds.')
        if self.user_deviation is not None and type(self.user_deviation) is not bool: raise ValueError('Invalid deviation filter.')
        if self.deviation_loss_min_cp is not None and (type(self.deviation_loss_min_cp) is not int or self.deviation_loss_min_cp < 0):
            raise ValueError('Use a nonnegative centipawn loss filter.')


def matches_opening_accuracy(result, query=OpeningAccuracyQuery()):
    if not result.applicable or result.user is None: return False
    if query.require_complete and not result.user.quality.complete: return False
    for prefix,value in (('accuracy',result.user.quality.accuracy),('adherence',result.user.adherence)):
        low,high=getattr(query,prefix+'_min'),getattr(query,prefix+'_max')
        if low is not None and (value is None or value < low): return False
        if high is not None and (value is None or value > high): return False
    user_rows=tuple(row for row in result.moves if row.party=='user' and row.book.deviation)
    if query.user_deviation is not None and bool(user_rows)!=query.user_deviation: return False
    if query.deviation_loss_min_cp is not None and not any(row.eval_loss_cp is not None and row.eval_loss_cp >= query.deviation_loss_min_cp for row in user_rows): return False
    if query.variation_name and not any(query.variation_name == node.name for row in result.moves
            if row.book.played_move_in_book and not row.book.variation_after.ambiguous
            for node in row.book.variation_after.path): return False
    return True
