"""ドメイン層（純粋なビジネス規則）.

外部 I/O・フレームワークに依存しない決定的な関数だけを置く.
- fsm: 対応状態の遷移規則（有限状態機械）
- triage: 未対応検知のトリアージ採点

adapters/services はこの層に依存してよいが, この層は他層に依存しない.
"""

from app.domain.fsm import assert_transition, can_transition
from app.domain.triage import compute_triage_score

__all__ = ["assert_transition", "can_transition", "compute_triage_score"]
