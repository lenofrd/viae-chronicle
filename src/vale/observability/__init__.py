"""观察层：只读事件流查看器（任务 07）。

纯读侧工具，不写库、不建表、不改模拟逻辑。按职责拆分：
  - query.py   筛选纯函数
  - render.py  中文渲染（含兜底与降级标记）
  - export.py  Markdown / CSV / JSONL 导出
  - viewer.py  只读存储 + 高层组合（日期换算走 calendar.py）
"""
