"""
服务重启辅助脚本
用于优雅地重启ICP查询服务
"""
import sys
import os
import time
import subprocess
import signal


def restart_service():
    """重启服务"""
    print("=" * 50)
    print("ICP查询服务 - 重启助手")
    print("=" * 50)
    
    # 获取当前Python解释器和主脚本路径
    python = sys.executable
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icpApi.py')
    
    print(f"\nPython解释器: {python}")
    print(f"主脚本路径: {script}")
    
    # 等待旧进程完全退出
    print("\n等待旧进程退出...")
    time.sleep(2)
    
    # 启动新进程
    print("启动新服务进程...")
    try:
        if os.name == 'nt':  # Windows
            # Windows: 在新控制台窗口启动
            subprocess.Popen(
                [python, script],
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        else:  # Linux/Unix
            # Linux: 后台启动
            subprocess.Popen(
                [python, script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        
        print("✓ 新服务进程已启动")
        print("\n重启完成！")
        time.sleep(2)
        
    except Exception as e:
        print(f"✗ 启动失败: {e}")
        input("\n按回车键退出...")


if __name__ == "__main__":
    try:
        restart_service()
    except KeyboardInterrupt:
        print("\n\n用户取消操作")
    except Exception as e:
        print(f"\n重启过程出错: {e}")
        input("\n按回车键退出...")

