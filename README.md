# 慢慢赚钱 · 今日价值弧

一个本地优先的 Windows 桌面小组件：它把一天的工作节奏画成一条弧，让你在抬眼之间看见今天已经积累的价值。

慢慢赚钱是独立设计与实现的开源项目。全部代码、界面结构、中文文案和视觉元素均从零编写；没有复制其他项目的代码、素材、界面或文案。它不接入网络、不使用分析服务，也不含任何个人身份信息。你填入的数字和工作时间只保存在自己的电脑中。

## 为什么是慢慢赚钱

与只显示一个不断跳动的数不同，慢慢赚钱把注意力放在“节奏感”上：

- 深色轨道搭配珊瑚色到薄荷绿的进度弧，金额、目标和进度一眼可读。
- 支持最多四段工作时段，午休、晚间班和跨午夜班次都能如实扣除。
- 显示下一段开始时间或距离收工的时间，并依早、中、晚给出不同的轻提示。
- 每周工作日可自行设置；休息日不会继续累计。
- 第一次打开只需填五项内容；之后可点击右下角随时调整。
- 可拖动、可置顶、自动记住位置；`Ctrl + ,` 打开设置，`Esc` 退出。

## 隐私承诺

- 不联网：项目没有网络请求、账号体系或遥测代码。
- 不收集：不会读取浏览记录、文件内容、剪贴板或系统身份信息。
- 仅本地保存：配置位于 `%LOCALAPPDATA%\慢慢赚钱\settings.json`（Windows）。删除该文件即可恢复默认状态。
- 可安全开源：仓库不保存你的配置、薪酬、窗口位置、用户名、邮箱或任何密钥。

## 快速开始

需要 Python 3.10 或更新版本，并确保安装时包含 `tkinter`（Windows 官方 Python 安装包默认包含）。

```powershell
python manmanzhuanqian.py
```

也可以双击 `run.bat`。首次运行会出现一个小表单，填入月薪、计薪工作日、两个工作时段和每周工作日即可开始。

## 计算方式

```text
日目标 = 月薪 ÷ 每月计薪工作日
今日价值 = 日目标 × 已完成的有效工作时长 ÷ 当天计划有效工作时长
```

只有排定的工作时段会累计；两个时段之间的休息时间不会计入。若结束时间早于开始时间，例如 `22:00 - 06:00`，慢慢赚钱会把它视为跨午夜班次。

## 打包为单文件程序

项目运行时没有第三方依赖。若希望打包成可分发的 Windows 程序，只在开发环境安装 PyInstaller：

```powershell
python -m pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --name manmanzhuanqian manmanzhuanqian.py
```

生成的程序位于 `dist\manmanzhuanqian.exe`（应用内仍显示“慢慢赚钱”）。仓库已包含 GitHub Actions：推送 `v*` 标签后会自动构建可下载的 Windows 文件。

## 为 GitHub 发布准备

1. 新建一个空的 GitHub 仓库，例如 `manmanzhuanqian`。
2. 将本目录全部推送到该仓库。
3. 在 GitHub 的仓库设置中启用 Actions。
4. 创建并推送一个形如 `v0.1.0` 的标签，即可触发自动发布。

在发布前，请保持 `.gitignore` 原样，且不要把本机的 `%LOCALAPPDATA%\慢慢赚钱\settings.json` 添加到仓库。

## 项目结构

```text
manmanzhuanqian/
├── manmanzhuanqian.py        # 应用界面和计算逻辑（仅标准库）
├── tests/test_schedule.py    # 核心排班计算测试
├── run.bat                   # Windows 直接启动
├── requirements-dev.txt      # 仅打包所需的开发依赖
└── .github/workflows/        # 测试和发布构建
```

## 开源许可

[MIT License](LICENSE)
