-- ============================================================
-- 智能课程表 Pro — 用户配置数据管理系统 数据库 Schema
-- ============================================================
-- 数据库: MySQL 8.0+
-- 字符集: utf8mb4 (支持 emoji 与全角字符)
-- 引擎:   InnoDB (支持事务、外键、行级锁)
--
-- 设计要点：
--   1. users          —— 用户账号表，密码使用 bcrypt + salt 哈希存储
--   2. user_configs   —— 用户配置表，与 users 一对一关联
--                        api_key 字段使用 Fernet (AES-128-CBC + HMAC-SHA256) 加密
--                        courses 字段以 JSON 数组形式存储（课程表数据）
--   3. 通过外键 + ON DELETE CASCADE 保证数据一致性
--   4. 索引设计：
--        - users.username 唯一索引（登录主键）
--        - user_configs.user_id 唯一外键（一对一）
--        - user_configs.updated_at 普通索引（按更新时间排序）
-- ============================================================

CREATE DATABASE IF NOT EXISTS timetable_pro
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE timetable_pro;

-- ============================================================
-- 用户账号表
-- ============================================================
DROP TABLE IF EXISTS user_configs;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '用户ID',
    username        VARCHAR(64)     NOT NULL COMMENT '登录用户名',
    password_hash   VARCHAR(255)    NOT NULL COMMENT 'bcrypt 哈希后的密码',
    salt            VARCHAR(64)     NOT NULL COMMENT '用户级盐值（与密码分离存储）',
    display_name    VARCHAR(128)    DEFAULT NULL COMMENT '显示名（可选）',
    is_active       TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '账号是否启用 1=是 0=否',
    last_login_at   DATETIME        DEFAULT NULL COMMENT '最近登录时间',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
    updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_users_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='用户账号表';


-- ============================================================
-- 用户配置表（与 users 一对一）
-- ============================================================
CREATE TABLE user_configs (
    user_id             BIGINT UNSIGNED NOT NULL COMMENT '关联 users.id',
    api_url             VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '大模型 API 地址',
    model_name          VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '大模型名称',
    api_key_encrypted   TEXT            DEFAULT NULL COMMENT 'Fernet 加密后的 API_KEY 密文',
    api_key_iv          VARCHAR(64)     DEFAULT NULL COMMENT '加密 IV（Fernet 自带，预留扩展）',
    courses_json        JSON            DEFAULT NULL COMMENT '课程数据 JSON 数组',
    semester_start      DATE            DEFAULT NULL COMMENT '学期起始日',
    total_weeks         INT UNSIGNED    DEFAULT 18 COMMENT '学期总周数',
    extra_settings      JSON            DEFAULT NULL COMMENT '扩展配置（前端自定义键值对）',
    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '首次创建时间',
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最近更新时间',
    PRIMARY KEY (user_id),
    CONSTRAINT fk_user_configs_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    KEY idx_user_configs_updated_at (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='用户配置表';


-- ============================================================
-- 可选：操作审计日志表（用于追踪配置变更历史）
-- ============================================================
CREATE TABLE IF NOT EXISTS user_config_audit (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id         BIGINT UNSIGNED NOT NULL,
    action          VARCHAR(32)     NOT NULL COMMENT 'create/update/delete',
    field_changed   VARCHAR(64)     DEFAULT NULL COMMENT '被修改的字段名',
    operator_ip     VARCHAR(45)     DEFAULT NULL COMMENT '操作者 IP',
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_audit_user_id (user_id),
    KEY idx_audit_created_at (created_at),
    CONSTRAINT fk_audit_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='用户配置变更审计日志';


-- ============================================================
-- 数据库初始化完成提示
-- ============================================================
SELECT '数据库 timetable_pro 初始化完成' AS message;
