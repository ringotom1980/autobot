/*M!999999\- enable the sandbox mode */ 
-- MariaDB dump 10.19-12.0.2-MariaDB, for Win64 (AMD64)
--
-- Host: 127.0.0.1    Database: u327657097_autobot_db
-- ------------------------------------------------------
-- Server version	11.8.3-MariaDB-log

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*M!100616 SET @OLD_NOTE_VERBOSITY=@@NOTE_VERBOSITY, NOTE_VERBOSITY=0 */;

--
-- Table structure for table `candles`
--

DROP TABLE IF EXISTS `candles`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `candles` (
  `symbol` varchar(16) NOT NULL,
  `interval` varchar(8) NOT NULL,
  `open_time` bigint(20) NOT NULL,
  `close_time` bigint(20) NOT NULL,
  `open` double NOT NULL,
  `high` double NOT NULL,
  `low` double NOT NULL,
  `close` double NOT NULL,
  `volume` double NOT NULL,
  `funding_rate` double DEFAULT NULL,
  PRIMARY KEY (`symbol`,`interval`,`close_time`),
  UNIQUE KEY `uq_candles_sic` (`symbol`,`interval`,`close_time`),
  KEY `idx_candles_si_ct` (`symbol`,`interval`,`close_time`),
  KEY `idx_candles_ct` (`close_time`),
  CONSTRAINT `chk_interval` CHECK (`interval` in ('1m','15m','30m','1h','4h')),
  CONSTRAINT `chk_interval_c` CHECK (`interval` in ('1m','15m','30m','1h','4h'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `decisions_log`
--

DROP TABLE IF EXISTS `decisions_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `decisions_log` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `session_id` bigint(20) DEFAULT NULL,
  `ts` bigint(20) NOT NULL,
  `symbol` varchar(16) NOT NULL,
  `interval` varchar(8) NOT NULL,
  `action` enum('LONG','SHORT','HOLD') NOT NULL,
  `is_flat` tinyint(1) NOT NULL DEFAULT 1,
  `E_long` double DEFAULT NULL,
  `E_short` double DEFAULT NULL,
  `template_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_sess` (`session_id`),
  KEY `idx_time` (`ts`),
  KEY `idx_sym_iv` (`symbol`,`interval`),
  KEY `idx_dec_sit` (`symbol`,`interval`,`ts`)
) ENGINE=InnoDB AUTO_INCREMENT=2872 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `evolution_events`
--

DROP TABLE IF EXISTS `evolution_events`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `evolution_events` (
  `event_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `ts` bigint(20) NOT NULL,
  `action` enum('MUTATE','CROSS','RANDOM','FREEZE','UNFREEZE') NOT NULL,
  `source_template_ids` varchar(64) DEFAULT NULL,
  `new_template_id` bigint(20) DEFAULT NULL,
  `notes` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`event_id`),
  KEY `idx_ev_ts` (`ts`),
  KEY `idx_ev_action` (`action`),
  KEY `idx_ev_newtid` (`new_template_id`)
) ENGINE=InnoDB AUTO_INCREMENT=21 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `features`
--

DROP TABLE IF EXISTS `features`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `features` (
  `symbol` varchar(16) NOT NULL,
  `interval` varchar(8) NOT NULL,
  `close_time` bigint(20) NOT NULL,
  `rsi` double DEFAULT NULL,
  `macd_dif` double DEFAULT NULL,
  `macd_dea` double DEFAULT NULL,
  `macd_hist` double DEFAULT NULL,
  `k` double DEFAULT NULL,
  `d` double DEFAULT NULL,
  `kd_diff` double DEFAULT NULL,
  `vol_ratio` double DEFAULT NULL,
  `atr_pct` double DEFAULT NULL,
  `slope` double DEFAULT NULL,
  `range_pct` double DEFAULT NULL,
  `regime` tinyint(4) DEFAULT NULL,
  PRIMARY KEY (`symbol`,`interval`,`close_time`),
  UNIQUE KEY `uq_features_sic` (`symbol`,`interval`,`close_time`),
  CONSTRAINT `chk_interval` CHECK (`interval` in ('1m','15m','30m','1h')),
  CONSTRAINT `chk_interval_f` CHECK (`interval` in ('1m','15m','30m','1h','4h'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `job_progress`
--

DROP TABLE IF EXISTS `job_progress`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `job_progress` (
  `job_id` varchar(64) NOT NULL,
  `phase` varchar(32) NOT NULL,
  `symbol` varchar(16) NOT NULL,
  `interval` varchar(8) NOT NULL,
  `step` int(11) NOT NULL,
  `total` int(11) NOT NULL,
  `pct` double NOT NULL,
  `updated_at` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`job_id`),
  KEY `idx_job_updated` (`job_id`,`updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `orders`
--

DROP TABLE IF EXISTS `orders`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `orders` (
  `order_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `symbol` varchar(16) NOT NULL,
  `side` enum('BUY','SELL') NOT NULL,
  `type` varchar(16) NOT NULL,
  `qty` double NOT NULL,
  `price` double NOT NULL,
  `status` varchar(16) NOT NULL,
  `placed_at` bigint(20) NOT NULL,
  `filled_qty` double DEFAULT 0,
  `avg_price` double DEFAULT 0,
  `exch_order_id` varchar(64) DEFAULT NULL,
  `reason` varchar(64) DEFAULT NULL,
  `session_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`order_id`),
  KEY `idx_ord_session` (`session_id`)
) ENGINE=InnoDB AUTO_INCREMENT=106 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `positions`
--

DROP TABLE IF EXISTS `positions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `positions` (
  `pos_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `symbol` varchar(16) NOT NULL,
  `direction` enum('LONG','SHORT') NOT NULL,
  `entry_price` double NOT NULL,
  `qty` double NOT NULL,
  `margin_type` enum('ISOLATED','CROSSED') NOT NULL DEFAULT 'ISOLATED',
  `leverage` int(11) NOT NULL,
  `status` enum('OPEN','CLOSED') NOT NULL,
  `opened_at` bigint(20) NOT NULL,
  `closed_at` bigint(20) DEFAULT NULL,
  `pnl_after_cost` double DEFAULT NULL,
  `interval` varchar(8) DEFAULT NULL,
  `template_id` bigint(20) DEFAULT NULL,
  `regime_entry` tinyint(4) DEFAULT NULL,
  `opened_bar_ms` int(11) DEFAULT NULL,
  `peak_price` double DEFAULT NULL,
  `session_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`pos_id`),
  KEY `idx_pos_open` (`symbol`,`status`,`opened_at`),
  KEY `idx_pos_session` (`session_id`)
) ENGINE=InnoDB AUTO_INCREMENT=113 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `risk_journal`
--

DROP TABLE IF EXISTS `risk_journal`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `risk_journal` (
  `ts` bigint(20) NOT NULL,
  `rule` varchar(64) NOT NULL,
  `detail` text DEFAULT NULL,
  `level` enum('INFO','WARN','CRIT') NOT NULL,
  `session_id` bigint(20) DEFAULT NULL,
  KEY `idx_risk_ts` (`ts`),
  KEY `idx_risk_session` (`session_id`),
  KEY `idx_risk_sess` (`session_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `run_sessions`
--

DROP TABLE IF EXISTS `run_sessions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `run_sessions` (
  `session_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `started_at` bigint(20) NOT NULL,
  `stopped_at` bigint(20) DEFAULT NULL,
  `mode` enum('SIM','LIVE') NOT NULL DEFAULT 'SIM',
  `note` text DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (`session_id`),
  KEY `idx_active` (`is_active`),
  KEY `idx_started` (`started_at`),
  KEY `idx_active_started` (`is_active`,`started_at`),
  KEY `idx_mode_started` (`mode`,`started_at`)
) ENGINE=InnoDB AUTO_INCREMENT=29 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `settings`
--

DROP TABLE IF EXISTS `settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `settings` (
  `id` tinyint(4) NOT NULL DEFAULT 1,
  `symbols_json` longtext NOT NULL CHECK (json_valid(`symbols_json`)),
  `intervals_json` longtext NOT NULL CHECK (json_valid(`intervals_json`)),
  `leverage_json` longtext NOT NULL CHECK (json_valid(`leverage_json`)),
  `invest_usdt_json` longtext NOT NULL CHECK (json_valid(`invest_usdt_json`)),
  `max_risk_pct` double NOT NULL DEFAULT 0.01,
  `max_daily_dd_pct` double NOT NULL DEFAULT 0.03,
  `hard_sl_pct` double DEFAULT NULL,
  `trail_backoff_pct` double DEFAULT NULL,
  `trail_trigger_pct` double DEFAULT NULL,
  `max_consec_losses` int(11) NOT NULL DEFAULT 4,
  `entry_threshold` double NOT NULL DEFAULT 0.3,
  `reverse_gap` double NOT NULL DEFAULT 0.2,
  `cooldown_bars` int(11) NOT NULL DEFAULT 2,
  `min_hold_bars` int(11) NOT NULL DEFAULT 2,
  `max_hold_bars` int(11) DEFAULT NULL,
  `is_enabled` tinyint(1) NOT NULL DEFAULT 1,
  `updated_at` timestamp NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  `trade_mode` enum('SIM','LIVE') NOT NULL DEFAULT 'SIM',
  `current_session_id` bigint(20) DEFAULT NULL,
  `live_armed` tinyint(1) NOT NULL DEFAULT 0,
  `fee_rate` decimal(10,8) NOT NULL DEFAULT 0.00040000,
  `slip_rate` decimal(10,8) NOT NULL DEFAULT 0.00050000,
  `adv_enabled` tinyint(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `template_stats`
--

DROP TABLE IF EXISTS `template_stats`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `template_stats` (
  `template_id` bigint(20) NOT NULL,
  `regime` tinyint(4) NOT NULL,
  `n_trades` int(11) DEFAULT 0,
  `reward_sum` double DEFAULT 0,
  `reward_mean` double DEFAULT 0,
  `reward_var` double DEFAULT 0,
  `last_used_at` bigint(20) DEFAULT NULL,
  `is_frozen` tinyint(4) DEFAULT 0,
  `sum_reward` double NOT NULL DEFAULT 0,
  `last_pnl` double NOT NULL DEFAULT 0,
  `last_exit_ts` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`template_id`,`regime`),
  KEY `idx_ts_template` (`template_id`),
  KEY `idx_ts_last_used` (`last_used_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `templates`
--

DROP TABLE IF EXISTS `templates`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `templates` (
  `template_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `version` int(11) NOT NULL,
  `side` enum('LONG','SHORT') NOT NULL,
  `rsi_bin` varchar(16) DEFAULT NULL,
  `macd_bin` varchar(16) DEFAULT NULL,
  `kd_bin` varchar(16) DEFAULT NULL,
  `vol_bin` varchar(16) DEFAULT NULL,
  `extra` longtext DEFAULT NULL CHECK (json_valid(`extra`)),
  `status` enum('ACTIVE','FROZEN') NOT NULL,
  `created_at` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`template_id`),
  KEY `idx_templates_status` (`status`)
) ENGINE=InnoDB AUTO_INCREMENT=27 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `trades_log`
--

DROP TABLE IF EXISTS `trades_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `trades_log` (
  `trade_id` bigint(20) NOT NULL AUTO_INCREMENT,
  `symbol` varchar(16) NOT NULL,
  `template_id` bigint(20) DEFAULT NULL,
  `regime` tinyint(4) DEFAULT NULL,
  `interval` varchar(8) NOT NULL,
  `entry_ts` bigint(20) NOT NULL,
  `exit_ts` bigint(20) DEFAULT NULL,
  `entry_price` double NOT NULL,
  `exit_price` double DEFAULT NULL,
  `qty` double NOT NULL DEFAULT 0,
  `fee` double DEFAULT 0,
  `slippage` double DEFAULT 0,
  `funding_fee` double DEFAULT 0,
  `pnl_after_cost` double DEFAULT NULL,
  `risk_used` double DEFAULT NULL,
  `reward` double DEFAULT NULL,
  `market_features_json` longtext DEFAULT NULL CHECK (json_valid(`market_features_json`)),
  `session_id` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`trade_id`),
  KEY `idx_tl_time` (`symbol`,`interval`,`entry_ts`),
  KEY `idx_tl_exit_ts` (`exit_ts`),
  KEY `idx_tl_siet` (`symbol`,`interval`,`exit_ts`),
  KEY `idx_tpl` (`template_id`),
  KEY `idx_tl_session` (`session_id`)
) ENGINE=InnoDB AUTO_INCREMENT=112 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Temporary table structure for view `v_evolution_events_7d`
--

DROP TABLE IF EXISTS `v_evolution_events_7d`;
/*!50001 DROP VIEW IF EXISTS `v_evolution_events_7d`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `v_evolution_events_7d` AS SELECT
 1 AS `d`,
  1 AS `n_mutate`,
  1 AS `n_cross`,
  1 AS `n_freeze` */;
SET character_set_client = @saved_cs_client;

--
-- Temporary table structure for view `v_evolution_events_recent`
--

DROP TABLE IF EXISTS `v_evolution_events_recent`;
/*!50001 DROP VIEW IF EXISTS `v_evolution_events_recent`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `v_evolution_events_recent` AS SELECT
 1 AS `event_id`,
  1 AS `ts`,
  1 AS `action`,
  1 AS `source_template_ids`,
  1 AS `new_template_id`,
  1 AS `notes` */;
SET character_set_client = @saved_cs_client;

--
-- Temporary table structure for view `v_templates_pool_status`
--

DROP TABLE IF EXISTS `v_templates_pool_status`;
/*!50001 DROP VIEW IF EXISTS `v_templates_pool_status`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `v_templates_pool_status` AS SELECT
 1 AS `status`,
  1 AS `c` */;
SET character_set_client = @saved_cs_client;

--
-- Dumping events for database 'u327657097_autobot_db'
--

--
-- Dumping routines for database 'u327657097_autobot_db'
--

--
-- Final view structure for view `v_evolution_events_7d`
--

/*!50001 DROP VIEW IF EXISTS `v_evolution_events_7d`*/;
/*!50001 SET @saved_cs_client          = @@character_set_client */;
/*!50001 SET @saved_cs_results         = @@character_set_results */;
/*!50001 SET @saved_col_connection     = @@collation_connection */;
/*!50001 SET character_set_client      = utf8mb4 */;
/*!50001 SET character_set_results     = utf8mb4 */;
/*!50001 SET collation_connection      = utf8mb4_unicode_ci */;
/*!50001 CREATE ALGORITHM=UNDEFINED */
/*!50013 DEFINER=`u327657097_autobot_admin`@`127.0.0.1` SQL SECURITY DEFINER */
/*!50001 VIEW `v_evolution_events_7d` AS select date_format(from_unixtime(`evolution_events`.`ts` / 1000),'%Y-%m-%d') AS `d`,cast(sum(`evolution_events`.`action` = 'MUTATE') as unsigned) AS `n_mutate`,cast(sum(`evolution_events`.`action` = 'CROSS') as unsigned) AS `n_cross`,cast(sum(`evolution_events`.`action` = 'FREEZE') as unsigned) AS `n_freeze` from `evolution_events` where `evolution_events`.`ts` >= unix_timestamp(curdate() - interval 6 day) * 1000 group by date_format(from_unixtime(`evolution_events`.`ts` / 1000),'%Y-%m-%d') order by date_format(from_unixtime(`evolution_events`.`ts` / 1000),'%Y-%m-%d') */;
/*!50001 SET character_set_client      = @saved_cs_client */;
/*!50001 SET character_set_results     = @saved_cs_results */;
/*!50001 SET collation_connection      = @saved_col_connection */;

--
-- Final view structure for view `v_evolution_events_recent`
--

/*!50001 DROP VIEW IF EXISTS `v_evolution_events_recent`*/;
/*!50001 SET @saved_cs_client          = @@character_set_client */;
/*!50001 SET @saved_cs_results         = @@character_set_results */;
/*!50001 SET @saved_col_connection     = @@collation_connection */;
/*!50001 SET character_set_client      = utf8mb4 */;
/*!50001 SET character_set_results     = utf8mb4 */;
/*!50001 SET collation_connection      = utf8mb4_unicode_ci */;
/*!50001 CREATE ALGORITHM=UNDEFINED */
/*!50013 DEFINER=`u327657097_autobot_admin`@`127.0.0.1` SQL SECURITY DEFINER */
/*!50001 VIEW `v_evolution_events_recent` AS select `evolution_events`.`event_id` AS `event_id`,`evolution_events`.`ts` AS `ts`,`evolution_events`.`action` AS `action`,`evolution_events`.`source_template_ids` AS `source_template_ids`,`evolution_events`.`new_template_id` AS `new_template_id`,`evolution_events`.`notes` AS `notes` from `evolution_events` order by `evolution_events`.`event_id` desc limit 50 */;
/*!50001 SET character_set_client      = @saved_cs_client */;
/*!50001 SET character_set_results     = @saved_cs_results */;
/*!50001 SET collation_connection      = @saved_col_connection */;

--
-- Final view structure for view `v_templates_pool_status`
--

/*!50001 DROP VIEW IF EXISTS `v_templates_pool_status`*/;
/*!50001 SET @saved_cs_client          = @@character_set_client */;
/*!50001 SET @saved_cs_results         = @@character_set_results */;
/*!50001 SET @saved_col_connection     = @@collation_connection */;
/*!50001 SET character_set_client      = utf8mb4 */;
/*!50001 SET character_set_results     = utf8mb4 */;
/*!50001 SET collation_connection      = utf8mb4_unicode_ci */;
/*!50001 CREATE ALGORITHM=UNDEFINED */
/*!50013 DEFINER=`u327657097_autobot_admin`@`127.0.0.1` SQL SECURITY DEFINER */
/*!50001 VIEW `v_templates_pool_status` AS select `templates`.`status` AS `status`,count(0) AS `c` from `templates` group by `templates`.`status` */;
/*!50001 SET character_set_client      = @saved_cs_client */;
/*!50001 SET character_set_results     = @saved_cs_results */;
/*!50001 SET collation_connection      = @saved_col_connection */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*M!100616 SET NOTE_VERBOSITY=@OLD_NOTE_VERBOSITY */;

-- Dump completed on 2025-10-08 17:43:30
