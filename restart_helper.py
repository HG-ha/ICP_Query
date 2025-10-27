"""
服务重启辅助脚本
用于优雅地重启ICP查询服务
"""
import sys
import os
import time
import subprocess
import signal


def is_frozen():
    """检测是否运行在打包后的环境（Nuitka、PyInstaller等）"""
    # Nuitka 打包后，__file__ 可能不存在或指向临时位置
    # sys.frozen 属性存在表示被打包
    return getattr(sys, 'frozen', False) or not sys.executable.lower().endswith(('python.exe', 'python', 'pythonw.exe'))


def get_executable_path():
    """获取可执行文件路径"""
    if is_frozen():
        # 打包后的情况：sys.executable 就是可执行文件本身
        return sys.executable
    else:
        # 未打包的情况：返回 icpApi.py 的路径
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icpApi.py')


def restart_service():
    """重启服务"""
    print("=" * 50)
    print("ICP查询服务 - 重启助手")
    print("=" * 50)
    
    frozen = is_frozen()
    
    if frozen:
        # 打包后的情况：直接运行可执行文件
        executable = get_executable_path()
        print(f"\n运行模式: 打包模式")
        print(f"可执行文件: {executable}")
        cmd = [executable]
    else:
        # 未打包的情况：使用 Python 解释器运行脚本
        python = sys.executable
        script = get_executable_path()
        print(f"\n运行模式: 脚本模式")
        print(f"Python解释器: {python}")
        print(f"主脚本路径: {script}")
        cmd = [python, script]
    
    # 等待旧进程完全退出
    print("\n等待旧进程退出...")
    time.sleep(2)
    
    # 启动新进程
    print("启动新服务进程...")
    try:
        if os.name == 'nt':  # Windows
            # Windows: 在新控制台窗口启动
            subprocess.Popen(
                cmd,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        else:  # Linux/Unix
            # Linux: 后台启动
            subprocess.Popen(
                cmd,
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

