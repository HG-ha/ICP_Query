# -*- coding: utf-8 -*-
import sqlite3
import json
from datetime import datetime
from mlog import logger
import os

class Database:
    def __init__(self, db_path="icp_history.db"):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """初始化数据库表"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 创建历史记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS search_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    search_type TEXT NOT NULL,
                    search_keyword TEXT NOT NULL,
                    result_count INTEGER DEFAULT 0,
                    search_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    result_data TEXT
                )
            ''')
            
            # 创建批量任务历史表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS batch_task_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_name TEXT NOT NULL UNIQUE,
                    task_type TEXT NOT NULL,
                    total_count INTEGER DEFAULT 0,
                    completed_count INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'running',
                    result_file TEXT,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finish_time TIMESTAMP
                )
            ''')
            
            # 创建索引
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_search_time 
                ON search_history(search_time DESC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_search_type 
                ON search_history(search_type)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_batch_create_time 
                ON batch_task_history(create_time DESC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_batch_status 
                ON batch_task_history(status)
            ''')
            
            conn.commit()
            conn.close()
            logger.info(f"数据库初始化完成: {self.db_path}")
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            raise
    
    def add_history(self, search_type, search_keyword, result_count=0, result_data=None):
        """添加搜索历史"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            result_json = json.dumps(result_data, ensure_ascii=False) if result_data else None
            
            cursor.execute('''
                INSERT INTO search_history (search_type, search_keyword, result_count, result_data)
                VALUES (?, ?, ?, ?)
            ''', (search_type, search_keyword, result_count, result_json))
            
            history_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            logger.info(f"添加历史记录成功: {search_type} - {search_keyword}")
            return history_id
        except Exception as e:
            logger.error(f"添加历史记录失败: {e}")
            return None
    
    def get_history(self, limit=100, offset=0, search_type=None):
        """获取历史记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if search_type:
                cursor.execute('''
                    SELECT id, search_type, search_keyword, result_count, search_time
                    FROM search_history
                    WHERE search_type = ?
                    ORDER BY search_time DESC
                    LIMIT ? OFFSET ?
                ''', (search_type, limit, offset))
            else:
                cursor.execute('''
                    SELECT id, search_type, search_keyword, result_count, search_time
                    FROM search_history
                    ORDER BY search_time DESC
                    LIMIT ? OFFSET ?
                ''', (limit, offset))
            
            rows = cursor.fetchall()
            conn.close()
            
            history_list = []
            for row in rows:
                history_list.append({
                    'id': row[0],
                    'search_type': row[1],
                    'search_keyword': row[2],
                    'result_count': row[3],
                    'search_time': row[4]
                })
            
            return history_list
        except Exception as e:
            logger.error(f"获取历史记录失败: {e}")
            return []
    
    def get_history_detail(self, history_id):
        """获取历史记录详情"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, search_type, search_keyword, result_count, search_time, result_data
                FROM search_history
                WHERE id = ?
            ''', (history_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                result_data = json.loads(row[5]) if row[5] else None
                return {
                    'id': row[0],
                    'search_type': row[1],
                    'search_keyword': row[2],
                    'result_count': row[3],
                    'search_time': row[4],
                    'result_data': result_data
                }
            return None
        except Exception as e:
            logger.error(f"获取历史记录详情失败: {e}")
            return None
    
    def delete_history(self, history_id):
        """删除历史记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM search_history WHERE id = ?', (history_id,))
            
            conn.commit()
            conn.close()
            
            logger.info(f"删除历史记录成功: ID={history_id}")
            return True
        except Exception as e:
            logger.error(f"删除历史记录失败: {e}")
            return False
    
    def clear_history(self, search_type=None):
        """清空历史记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if search_type:
                cursor.execute('DELETE FROM search_history WHERE search_type = ?', (search_type,))
            else:
                cursor.execute('DELETE FROM search_history')
            
            conn.commit()
            conn.close()
            
            logger.info(f"清空历史记录成功: {search_type if search_type else '全部'}")
            return True
        except Exception as e:
            logger.error(f"清空历史记录失败: {e}")
            return False
    
    def get_history_count(self, search_type=None):
        """获取历史记录总数"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if search_type:
                cursor.execute('SELECT COUNT(*) FROM search_history WHERE search_type = ?', (search_type,))
            else:
                cursor.execute('SELECT COUNT(*) FROM search_history')
            
            count = cursor.fetchone()[0]
            conn.close()
            
            return count
        except Exception as e:
            logger.error(f"获取历史记录总数失败: {e}")
            return 0
    
    # ============ 批量任务历史管理 ============
    
    def add_batch_task(self, task_name, task_type, total_count=0):
        """添加批量任务"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO batch_task_history (task_name, task_type, total_count, status)
                VALUES (?, ?, ?, 'running')
            ''', (task_name, task_type, total_count))
            
            task_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            logger.info(f"添加批量任务成功: {task_name}")
            return task_id
        except Exception as e:
            logger.error(f"添加批量任务失败: {e}")
            return None
    
    def update_batch_task(self, task_name, completed_count=None, success_count=None, 
                         status=None, result_file=None, finish_time=None):
        """更新批量任务"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if completed_count is not None:
                updates.append('completed_count = ?')
                params.append(completed_count)
            
            if success_count is not None:
                updates.append('success_count = ?')
                params.append(success_count)
            
            if status is not None:
                updates.append('status = ?')
                params.append(status)
            
            if result_file is not None:
                updates.append('result_file = ?')
                params.append(result_file)
            
            if finish_time is not None:
                updates.append('finish_time = ?')
                params.append(finish_time)
            
            updates.append('update_time = CURRENT_TIMESTAMP')
            params.append(task_name)
            
            sql = f"UPDATE batch_task_history SET {', '.join(updates)} WHERE task_name = ?"
            cursor.execute(sql, params)
            
            conn.commit()
            conn.close()
            
            return True
        except Exception as e:
            logger.error(f"更新批量任务失败: {e}")
            return False
    
    def get_batch_tasks(self, limit=100, offset=0, status=None):
        """获取批量任务列表"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if status:
                cursor.execute('''
                    SELECT id, task_name, task_type, total_count, completed_count, 
                           success_count, status, result_file, create_time, update_time, finish_time
                    FROM batch_task_history
                    WHERE status = ?
                    ORDER BY create_time DESC
                    LIMIT ? OFFSET ?
                ''', (status, limit, offset))
            else:
                cursor.execute('''
                    SELECT id, task_name, task_type, total_count, completed_count, 
                           success_count, status, result_file, create_time, update_time, finish_time
                    FROM batch_task_history
                    ORDER BY create_time DESC
                    LIMIT ? OFFSET ?
                ''', (limit, offset))
            
            rows = cursor.fetchall()
            conn.close()
            
            task_list = []
            for row in rows:
                task_list.append({
                    'id': row[0],
                    'task_name': row[1],
                    'task_type': row[2],
                    'total_count': row[3],
                    'completed_count': row[4],
                    'success_count': row[5],
                    'status': row[6],
                    'result_file': row[7],
                    'create_time': row[8],
                    'update_time': row[9],
                    'finish_time': row[10]
                })
            
            return task_list
        except Exception as e:
            logger.error(f"获取批量任务列表失败: {e}")
            return []
    
    def get_batch_task_detail(self, task_name):
        """获取批量任务详情"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, task_name, task_type, total_count, completed_count, 
                       success_count, status, result_file, create_time, update_time, finish_time
                FROM batch_task_history
                WHERE task_name = ?
            ''', (task_name,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    'id': row[0],
                    'task_name': row[1],
                    'task_type': row[2],
                    'total_count': row[3],
                    'completed_count': row[4],
                    'success_count': row[5],
                    'status': row[6],
                    'result_file': row[7],
                    'create_time': row[8],
                    'update_time': row[9],
                    'finish_time': row[10]
                }
            return None
        except Exception as e:
            logger.error(f"获取批量任务详情失败: {e}")
            return None
    
    def get_batch_tasks_count(self, status=None):
        """获取批量任务总数"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if status:
                cursor.execute('SELECT COUNT(*) FROM batch_task_history WHERE status = ?', (status,))
            else:
                cursor.execute('SELECT COUNT(*) FROM batch_task_history')
            
            count = cursor.fetchone()[0]
            conn.close()
            
            return count
        except Exception as e:
            logger.error(f"获取批量任务总数失败: {e}")
            return 0
    
    def delete_batch_task(self, task_name):
        """删除批量任务记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 先获取结果文件路径
            cursor.execute('SELECT result_file FROM batch_task_history WHERE task_name = ?', (task_name,))
            row = cursor.fetchone()
            result_file = row[0] if row else None
            
            # 删除数据库记录
            cursor.execute('DELETE FROM batch_task_history WHERE task_name = ?', (task_name,))
            
            conn.commit()
            conn.close()
            
            # 删除结果文件
            if result_file and os.path.exists(result_file):
                try:
                    os.remove(result_file)
                    logger.info(f"删除结果文件成功: {result_file}")
                except Exception as e:
                    logger.error(f"删除结果文件失败: {e}")
            
            logger.info(f"删除批量任务成功: {task_name}")
            return True
        except Exception as e:
            logger.error(f"删除批量任务失败: {e}")
            return False

