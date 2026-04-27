-- 测试数据库初始化脚本
-- 由 Docker MySQL 容器启动时自动执行

CREATE DATABASE IF NOT EXISTS testdb;
USE testdb;

-- 用户表
CREATE TABLE IF NOT EXISTS users (
  id INT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(100) NOT NULL COMMENT '用户名',
  email VARCHAR(100) UNIQUE NOT NULL COMMENT '邮箱',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
) COMMENT='用户表';

INSERT INTO users (name, email) VALUES
  ('张三', 'zhangsan@example.com'),
  ('李四', 'lisi@example.com'),
  ('王五', 'wangwu@example.com');

-- 订单表
CREATE TABLE IF NOT EXISTS orders (
  id INT PRIMARY KEY AUTO_INCREMENT,
  user_id INT NOT NULL COMMENT '用户ID',
  product VARCHAR(100) NOT NULL COMMENT '商品名称',
  amount DECIMAL(10,2) NOT NULL COMMENT '金额',
  status ENUM('pending','shipped','completed') DEFAULT 'pending' COMMENT '状态',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
) COMMENT='订单表';

INSERT INTO orders (user_id, product, amount, status) VALUES
  (1, 'iPhone 15',   6999.00, 'completed'),
  (2, 'MacBook Pro', 12999.00, 'completed'),
  (1, 'AirPods',     1299.00, 'shipped'),
  (3, 'iPad',        4599.00, 'pending');
