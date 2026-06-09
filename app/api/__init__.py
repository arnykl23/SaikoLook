"""API 層（ルート・依存・認証・スキーマ）.

ルーター（routes_emails / routes_messages）, 依存（deps）, JWT 認証（auth）,
入出力スキーマ（schemas）を束ねる. main.py が router を include し,
ドメイン例外を HTTP へ写像する.
"""
