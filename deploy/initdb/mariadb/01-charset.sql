-- 兜底：把业务库统一到 utf8mb4 / utf8mb4_unicode_ci。
-- 服务器级默认已在 docker-compose.yml 的 command 里设置，这里只处理已存在的业务库，
-- 库名不硬编码（随 MARIADB_DATABASE 变化）。
-- 仅在数据目录为空、容器首次初始化时执行（/docker-entrypoint-initdb.d）。
SET @sql := IFNULL((
  SELECT GROUP_CONCAT(
    CONCAT('ALTER DATABASE `', SCHEMA_NAME, '` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;')
    SEPARATOR ' '
  )
  FROM information_schema.SCHEMATA
  WHERE SCHEMA_NAME NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
), 'DO 0');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
