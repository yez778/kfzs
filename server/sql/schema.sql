-- ============================================================
-- 星途户外照明商城 · MySQL 8 建表脚本（由 SQLAlchemy 模型生成）
-- 数据库：doudian | 字符集：utf8mb4
-- ============================================================

CREATE DATABASE IF NOT EXISTS doudian DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE doudian;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- 表：after_sales_previews（11 列）

CREATE TABLE after_sales_previews (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(36) NOT NULL, 
	order_id VARCHAR(64) NOT NULL, 
	action VARCHAR(32) NOT NULL, 
	reason TEXT NOT NULL, 
	amount NUMERIC(12, 2) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	idempotency_key_hash VARCHAR(64), 
	after_sales_id VARCHAR(64), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：conversation_summaries（6 列）

CREATE TABLE conversation_summaries (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	session_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	summary TEXT NOT NULL, 
	message_count INTEGER NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (session_id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：human_tasks（7 列）

CREATE TABLE human_tasks (
	id VARCHAR(36) NOT NULL, 
	task_type VARCHAR(32) NOT NULL, 
	payload_json TEXT NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	reason TEXT, 
	created_at DATETIME NOT NULL, 
	reviewed_at DATETIME, 
	PRIMARY KEY (id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：inventory_alerts（7 列）

CREATE TABLE inventory_alerts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	sku_id VARCHAR(64) NOT NULL, 
	sku_name VARCHAR(255) NOT NULL, 
	current_stock INTEGER NOT NULL, 
	threshold INTEGER NOT NULL, 
	handled BOOL NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：knowledge_documents（11 列）

CREATE TABLE knowledge_documents (
	id VARCHAR(36) NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	product_model VARCHAR(128) NOT NULL, 
	page_count INTEGER NOT NULL, 
	chunk_count INTEGER NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	error TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：memory_consents（4 列）

CREATE TABLE memory_consents (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64) NOT NULL, 
	enabled BOOL NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (user_id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：memory_records（7 列）

CREATE TABLE memory_records (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id VARCHAR(64) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	content TEXT NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	importance NUMERIC(3, 2) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：product_inventory（7 列）

CREATE TABLE product_inventory (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	sku_id VARCHAR(64) NOT NULL, 
	product_id VARCHAR(32) NOT NULL, 
	sku_name VARCHAR(255) NOT NULL, 
	stock INTEGER NOT NULL, 
	threshold INTEGER NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (sku_id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：products（20 列）

CREATE TABLE products (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	product_id VARCHAR(32) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	subtitle VARCHAR(255) NOT NULL, 
	category VARCHAR(64) NOT NULL, 
	category_code VARCHAR(32) NOT NULL, 
	price NUMERIC(12, 2) NOT NULL, 
	original_price NUMERIC(12, 2) NOT NULL, 
	sales_count INTEGER NOT NULL, 
	cover TEXT NOT NULL, 
	cover_color VARCHAR(16) NOT NULL, 
	description TEXT NOT NULL, 
	gallery_json TEXT NOT NULL, 
	specs_json TEXT NOT NULL, 
	skus_json TEXT NOT NULL, 
	services_json TEXT NOT NULL, 
	tags_json TEXT NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	source_url TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (product_id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：users（9 列）

CREATE TABLE users (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	username VARCHAR(64) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	`role` VARCHAR(32) NOT NULL, 
	openid VARCHAR(64), 
	avatar_url VARCHAR(512) NOT NULL, 
	wallet_balance NUMERIC(12, 2) NOT NULL, 
	cart_json TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (username), 
	UNIQUE (openid)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：workflow_states（6 列）

CREATE TABLE workflow_states (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	session_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	phase VARCHAR(64) NOT NULL, 
	state_json TEXT NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (session_id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：chat_sessions（6 列）

CREATE TABLE chat_sessions (
	id VARCHAR(36) NOT NULL, 
	user_id INTEGER NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	created_at DATETIME NOT NULL, 
	handoff_status VARCHAR(16) NOT NULL, 
	handled_by INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(handled_by) REFERENCES users (id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：orders（17 列）

CREATE TABLE orders (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	order_id VARCHAR(64) NOT NULL, 
	user_id INTEGER, 
	customer VARCHAR(128) NOT NULL, 
	product VARCHAR(255) NOT NULL, 
	amount NUMERIC(12, 2) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	pay_method VARCHAR(32) NOT NULL, 
	ship_company VARCHAR(32) NOT NULL, 
	ship_company_name VARCHAR(64) NOT NULL, 
	logistics_code VARCHAR(64) NOT NULL, 
	shipped_at DATETIME, 
	received_at DATETIME, 
	refund_no VARCHAR(64) NOT NULL, 
	refunded_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (order_id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：payment_orders（16 列）

CREATE TABLE payment_orders (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	out_trade_no VARCHAR(48) NOT NULL, 
	order_id VARCHAR(64) NOT NULL, 
	user_id INTEGER NOT NULL, 
	amount_fen INTEGER NOT NULL, 
	description VARCHAR(255) NOT NULL, 
	openid VARCHAR(64) NOT NULL, 
	prepay_id VARCHAR(64) NOT NULL, 
	trade_state VARCHAR(16) NOT NULL, 
	transaction_id VARCHAR(64), 
	payer_result VARCHAR(16) NOT NULL, 
	fail_reason VARCHAR(64), 
	paid_at DATETIME, 
	expires_at DATETIME NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：messages（7 列）

CREATE TABLE messages (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	session_id VARCHAR(36) NOT NULL, 
	`role` VARCHAR(16) NOT NULL, 
	content TEXT NOT NULL, 
	citations_json TEXT NOT NULL, 
	product_cards_json TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES chat_sessions (id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 表：order_items（8 列）

CREATE TABLE order_items (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	order_db_id INTEGER NOT NULL, 
	product_id VARCHAR(32) NOT NULL, 
	sku_id VARCHAR(64) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	price NUMERIC(12, 2) NOT NULL, 
	quantity INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_db_id) REFERENCES orders (id)
)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;
