"""サービス層（ユースケースの結線）.

ポート（抽象）を組み合わせてユースケースを構成する. 具象 adapter には
依存せず, port 経由で受け取る（依存性注入）. 例:
- ingestion: MessageSource → Analyzer → Repository（取得→分析→保存）
- state_service: Repository に対する状態遷移ユースケース
"""
