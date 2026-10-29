# -*- coding: utf-8 -*-
"""从 SQLAlchemy 模型自动生成 MySQL 8 建表 SQL 与测试数据 SQL。

用法：cd server && python sql/generate_sql.py
产物：server/sql/schema.sql（建表 DDL）、server/sql/seed_data.sql（测试数据）
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.dialects.mysql import dialect  # noqa: E402
from sqlalchemy.schema import CreateTable  # noqa: E402

from app.data.showcase import PRODUCTS  # noqa: E402
from app.models import Base  # noqa: E402
from app.security import hash_password  # noqa: E402

OUT = Path(__file__).resolve().parent
ENGINE = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"


def _mysql_ddl(table) -> str:
    ddl = str(CreateTable(table).compile(dialect=dialect()))
    return ddl[:-1] + f" {ENGINE};"  # 去掉末尾分号，追加 ENGINE 行


def gen_schema() -> str:
    lines = [
        "-- ============================================================",
        "-- 星途户外照明商城 · MySQL 8 建表脚本（由 SQLAlchemy 模型生成）",
        "-- 数据库：doudian | 字符集：utf8mb4",
        "-- ============================================================",
        "",
        "CREATE DATABASE IF NOT EXISTS doudian DEFAULT CHARACTER SET utf8mb4",
        "  COLLATE utf8mb4_unicode_ci;",
        "",
        "USE doudian;",
        "",
        "SET NAMES utf8mb4;",
        "SET FOREIGN_KEY_CHECKS = 0;",
        "",
    ]
    for table in Base.metadata.sorted_tables:
        lines.append(f"-- 表：{table.name}（{len(table.columns)} 列）")
        lines.append(_mysql_ddl(table))
        lines.append("")
    lines.append("SET FOREIGN_KEY_CHECKS = 1;")
    lines.append("")
    return "\n".join(lines)


def gen_seed() -> str:
    lines = [
        "-- ============================================================",
        "-- 星途户外照明商城 · 测试数据（种子）",
        "-- 依赖 schema.sql 建表完成后执行",
        "-- ============================================================",
        "",
        "USE doudian;",
        "",
        "-- ---------- 1. 账号：管理员 / 员工 / 顾客 ----------",
        "INSERT INTO users (username, password_hash, role, openid, avatar_url, wallet_balance, cart_json, created_at) VALUES",
    ]
    accounts = [
        ("admin", "Admin@123456", "admin", "", "", 2000.0),
        ("staff", "Staff@123456", "staff", "", "", 2000.0),
        ("customer", "Customer@123", "customer", "", "", 2000.0),
    ]
    rows = []
    for username, pwd, role, openid, avatar, wallet in accounts:
        h = hash_password(pwd)
        rows.append(
            f"  ('{username}', '{h}', '{role}', '{openid}', '{avatar}', {wallet:.2f}, '[]', '2026-10-01 00:00:00')"
        )
    lines.append(",\n".join(rows) + ";")
    lines.append("")

    # ---------- 2. 商品 ----------
    lines.append("-- ---------- 2. 商品主数据（16 个 SKU 共 13 件在售商品） ----------")
    lines.append(
        "INSERT INTO products (product_id, title, subtitle, category, category_code, price, original_price, sales_count, cover, cover_color, description, gallery_json, specs_json, skus_json, services_json, tags_json, status, source_url, created_at) VALUES"
    )
    prows = []
    for p in PRODUCTS:
        cover = (p.get("cover") or "").replace("'", "''")
        desc = (p.get("description") or "").replace("'", "''")
        prows.append(
            "  ('{pid}', '{title}', '{sub}', '{cat}', '{cc}', {price}, {oprice}, {sales}, '{cover}', '{color}', '{desc}', '{gallery}', '{specs}', '{skus}', '{services}', '{tags}', '{status}', '{src}', '2026-10-01 00:00:00')".format(
                pid=p["product_id"],
                title=p["title"].replace("'", "''"),
                sub=(p.get("subtitle") or "").replace("'", "''"),
                cat=p.get("category", "柱头灯"),
                cc=p.get("category_code", "post"),
                price=float(p["price"]),
                oprice=float(p.get("original_price") or p["price"]),
                sales=p.get("sales_count", 0),
                cover=cover,
                color=p.get("cover_color", "#E5E7EB"),
                desc=desc,
                gallery=json.dumps(p.get("gallery", []), ensure_ascii=False).replace("'", "''"),
                specs=json.dumps(p.get("specs", []), ensure_ascii=False).replace("'", "''"),
                skus=json.dumps([{**s, "price": float(s["price"])} for s in p.get("skus", [])], ensure_ascii=False).replace("'", "''"),
                services=json.dumps(p.get("services", []), ensure_ascii=False).replace("'", "''"),
                tags=json.dumps(p.get("tags", []), ensure_ascii=False).replace("'", "''"),
                status=p.get("status", "on_sale"),
                src=(p.get("source_url") or "").replace("'", "''"),
            )
        )
    lines.append(",\n".join(prows) + ";")
    lines.append("")

    # ---------- 3. 库存 ----------
    lines.append("-- ---------- 3. SKU 库存 ----------")
    lines.append(
        "INSERT INTO product_inventory (sku_id, product_id, sku_name, stock, threshold, updated_at) VALUES"
    )
    irows = []
    for p in PRODUCTS:
        for sku in p.get("skus", []):
            irows.append(
                "  ('{sid}', '{pid}', '{name}', {stock}, {th}, '2026-10-01 00:00:00')".format(
                    sid=sku["sku_id"],
                    pid=p["product_id"],
                    name=p["title"].replace("'", "''"),
                    stock=sku.get("stock", 50),
                    th=sku.get("threshold", 5),
                )
            )
    lines.append(",\n".join(irows) + ";")
    lines.append("")

    # ---------- 4. 示例订单（含履约字段） ----------
    lines.append("-- ---------- 4. 示例订单（含发货/退款履约字段） ----------")
    lines.append(
        "INSERT INTO orders (order_id, user_id, customer, product, amount, status, pay_method, ship_company, ship_company_name, logistics_code, shipped_at, received_at, refund_no, refunded_at, created_at, updated_at) VALUES"
    )
    orders = [
        ("2026.10.1.10.0.1", 3, "张三", "太阳能柱头灯", 350.00, "paid", "wxpay_sandbox", "", "", "", None, None, "", None),
        ("2026.10.2.11.0.2", 3, "张三", "新中式太阳能柱头灯", 120.00, "paid", "wxpay_sandbox", "", "", "", None, None, "", None),
        ("2026.10.3.14.0.3", 3, "张三", "太阳能庭院灯", 180.00, "shipped", "wxpay_sandbox", "SF", "顺丰速运", "SF1234567890", "2026-10-05 09:30:00", None, "", None),
        ("2026.10.4.16.0.4", 3, "张三", "中式户外壁灯", 105.00, "completed", "wxpay_sandbox", "YTO", "圆通速递", "YT9876543210", "2026-10-06 10:00:00", "2026-10-08 18:00:00", "", None),
        ("2026.10.5.9.0.5", 3, "张三", "LED 户外壁灯", 100.00, "refunded", "wxpay_sandbox", "ZTO", "中通快递", "ZT5566778899", "2026-10-07 11:00:00", None, "RFD20261007001", "2026-10-09 12:00:00"),
        ("2026.10.6.15.0.6", 3, "张三", "太阳能柱头灯", 350.00, "unpaid", "wxpay_sandbox", "", "", "", None, None, "", None),
        ("2026.10.7.20.0.7", 3, "张三", "户外壁灯", 260.00, "cancelled", "wxpay_sandbox", "", "", "", None, None, "", None),
    ]
    orows = []
    for oid, uid, cust, prod, amt, status, pay, shipc, shipn, logi, shipped, received, rfno, rfat in orders:
        orows.append(
            "  ('{oid}', {uid}, '{cust}', '{prod}', {amt:.2f}, '{status}', '{pay}', '{shipc}', '{shipn}', '{logi}', {shipped}, {received}, '{rfno}', {rfat}, '2026-10-01 00:00:00', '2026-10-01 00:00:00')".format(
                oid=oid, uid=uid, cust=cust, prod=prod.replace("'", "''"), amt=amt,
                status=status, pay=pay, shipc=shipc, shipn=shipn, logi=logi,
                shipped=f"'{shipped}'" if shipped else "NULL",
                received=f"'{received}'" if received else "NULL",
                rfno=rfno, rfat=f"'{rfat}'" if rfat else "NULL",
            )
        )
    lines.append(",\n".join(orows) + ";")
    lines.append("")

    # ---------- 5. 支付单 ----------
    lines.append("-- ---------- 5. 微信支付单（沙箱模拟） ----------")
    lines.append(
        "INSERT INTO payment_orders (out_trade_no, order_id, user_id, amount_fen, description, openid, prepay_id, trade_state, transaction_id, payer_result, fail_reason, paid_at, expires_at, created_at, updated_at) VALUES"
    )
    pays = [
        ("20261001100001", "2026.10.1.10.0.1", 3, 35000, "星途户外照明-太阳能柱头灯", "", "wx_mock_1", "SUCCESS", "420000000120261000001", "SUCCESS", None, "2026-10-01 10:05:00", "2026-10-16 10:00:00"),
        ("20261003140003", "2026.10.3.14.0.3", 3, 18000, "星途户外照明-太阳能庭院灯", "", "wx_mock_3", "SUCCESS", "420000000120261000003", "SUCCESS", None, "2026-10-03 14:10:00", "2026-10-18 14:00:00"),
        ("20261005090005", "2026.10.5.9.0.5", 3, 10000, "星途户外照明-LED 户外壁灯", "", "wx_mock_5", "SUCCESS", "420000000120261000005", "SUCCESS", None, "2026-10-05 09:20:00", "2026-10-20 09:00:00"),
        ("20261006150006", "2026.10.6.15.0.6", 3, 35000, "星途户外照明-太阳能柱头灯", "", "wx_mock_6", "NOTPAY", None, "SUCCESS", None, None, "2026-10-21 15:00:00"),
        ("20261007200007", "2026.10.7.20.0.7", 3, 26000, "星途户外照明-户外壁灯", "", "wx_mock_7", "CLOSED", None, "SUCCESS", None, None, "2026-10-22 20:00:00"),
    ]
    prows2 = []
    for ot, oid, uid, fen, desc, openid, pp, ts, txid, pr, fr, paid, exp in pays:
        prows2.append(
            "  ('{ot}', '{oid}', {uid}, {fen}, '{desc}', '{openid}', '{pp}', '{ts}', {txid}, '{pr}', {fr}, {paid}, '{exp}', '2026-10-01 00:00:00', '2026-10-01 00:00:00')".format(
                ot=ot, oid=oid, uid=uid, fen=fen, desc=desc.replace("'", "''"),
                openid=openid, pp=pp, ts=ts,
                txid=f"'{txid}'" if txid else "NULL",
                pr=pr, fr=f"'{fr}'" if fr else "NULL",
                paid=f"'{paid}'" if paid else "NULL", exp=exp,
            )
        )
    lines.append(",\n".join(prows2) + ";")
    lines.append("")

    # ---------- 6. 会话与消息 ----------
    lines.append("-- ---------- 6. 客服会话与消息 ----------")
    lines.append("INSERT INTO chat_sessions (id, user_id, title, handoff_status, handled_by, created_at) VALUES")
    lines.append("  ('6f1d2a3b-0001-4c5d-9e8f-123456789001', 3, '太阳能灯咨询', 'none', NULL, '2026-10-01 10:00:00'),")
    lines.append("  ('6f1d2a3b-0002-4c5d-9e8f-123456789002', 3, '退款进度查询', 'closed', NULL, '2026-10-02 10:00:00');")
    lines.append("")
    lines.append("INSERT INTO messages (session_id, role, content, citations_json, product_cards_json, created_at) VALUES")
    lines.append("  ('6f1d2a3b-0001-4c5d-9e8f-123456789001', 'user', '有哪些适合庭院的太阳能灯？', '[]', '[]', '2026-10-01 10:00:01'),")
    lines.append("  ('6f1d2a3b-0001-4c5d-9e8f-123456789001', 'assistant', '推荐太阳能庭院灯与太阳能柱头灯，防水等级 IP65，天黑自动亮灯。', '[\"商品知识库\"]', '[]', '2026-10-01 10:00:03'),")
    lines.append("  ('6f1d2a3b-0002-4c5d-9e8f-123456789002', 'user', '我的退款到哪一步了？', '[]', '[]', '2026-10-02 10:00:01'),")
    lines.append("  ('6f1d2a3b-0002-4c5d-9e8f-123456789002', 'assistant', '您的订单已退款成功，退款单号 RFD20261007001，1-3 个工作日原路退回。', '[]', '[]', '2026-10-02 10:00:05');")
    lines.append("")

    # ---------- 7. 知识文档 ----------
    lines.append("-- ---------- 7. 知识库文档 ----------")
    lines.append(
        "INSERT INTO knowledge_documents (id, filename, title, product_model, page_count, chunk_count, content_hash, status, error, created_at, updated_at) VALUES"
    )
    lines.append("  ('a1b2c3d4-0001-4e5f-9a0b-112233445566', '太阳能柱头灯使用手册.pdf', '太阳能柱头灯使用手册', '太阳能柱头灯', 12, 24, 'sha256_mock_1', 'processed', NULL, '2026-10-01 09:00:00', '2026-10-01 09:00:00'),")
    lines.append("  ('a1b2c3d4-0002-4e5f-9a0b-112233445577', '售后服务政策.pdf', '售后服务政策', '通用', 8, 16, 'sha256_mock_2', 'processed', NULL, '2026-10-01 09:00:00', '2026-10-01 09:00:00');")
    lines.append("")

    # ---------- 8. 库存预警 / 记忆 ----------
    lines.append("-- ---------- 8. 库存预警与用户记忆 ----------")
    lines.append("INSERT INTO inventory_alerts (sku_id, sku_name, current_stock, threshold, handled, created_at) VALUES")
    lines.append("  ('SKU-P10009', '太阳能柱头灯户外防水现代简约LED庭院灯福字方形围墙灯后现代', 3, 5, 0, '2026-10-03 08:00:00');")
    lines.append("")
    lines.append("INSERT INTO memory_records (user_id, kind, content, source, importance, created_at) VALUES")
    lines.append("  ('3', 'semantic', '顾客偏好太阳能类庭院灯，关注防水等级', 'user_explicit', 0.8, '2026-10-02 11:00:00');")
    lines.append("")
    lines.append("-- ===== 测试数据导入完成 =====")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    (OUT / "schema.sql").write_text(gen_schema(), encoding="utf-8")
    (OUT / "seed_data.sql").write_text(gen_seed(), encoding="utf-8")
    print("已生成:")
    print(f"  {OUT / 'schema.sql'}")
    print(f"  {OUT / 'seed_data.sql'}")


if __name__ == "__main__":
    main()
