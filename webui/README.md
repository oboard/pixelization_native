# Pixel Review 本地标注工作台

使用 Node.js 24 或更高版本，在 `webui/` 中运行：

```bash
pnpm install
pnpm dev
```

打开终端显示的本地地址。首页和 `/annotate` 是纠错工作台；原拼豆生成器保留在 `/generator`。生产构建可用 `pnpm build && pnpm start`，默认监听 4173 端口。

## 标注流程

1. 点击「导入样本」，上传原图 PNG。预测图和样本 ID 均可留空：服务端调用 Python Test PRO 模型生成 24、52、78、104 四种尺寸，自动使用下一个数字 ID，并把新样本追加到队列末尾。也可提供已有预测 PNG；预测图必须是逻辑像素尺寸，最大 256×256。导入时将预测图逐像素映射到固定 MARD 291 色板；原始预测 PNG 单独保留。自动推理需要本机 Apple MPS GPU、`.venv` Python 环境和模型权重。
2. 在右侧画布用铅笔、橡皮、取色、直线、矩形轮廓和连通区域填充修正。铅笔和橡皮可拖动连续绘制，直线与矩形拖动时预览，松开后整次操作可一步撤销。「一键去背景」沿用生成器页面的算法：统计边缘主色，只移除与边缘连通的同色区域。「净化彩边」针对单色图案：识别占优势的鲜艳主色及其最大连通块，将外侧一格变为纯黑轮廓，其余杂色变为透明。多色图案无法可靠识别时会保持原图。这两种操作均可撤销。每格对应一个逻辑像素，透明像素的 palette index 为 `-1`。空格拖动平移，滚轮缩放；`B`、`E`、`I`、`L`、`R`、`F` 切换工具，`G` 去背景，`J` 净化彩边，`Ctrl/Cmd+Z` 撤销，`Ctrl/Cmd+Shift+Z` 重做。
3. 「保存」生成修正图、二值 edit mask 和元数据；「直接通过」生成零修改的标注；「跳过 / 下一张」暂不更改状态。`S`、`A`、`N` 对应上述操作。

用仓库中的 Python 模型和本机 Apple MPS GPU 为 `data/pixel_art/non_pixel/` 的每张图生成 24、52、78、104 四种逻辑尺寸：

```bash
../.venv/bin/python ../scripts/seed_annotation_samples.py
```

脚本只加载一次 `TestProInference`，将预测图和像素索引写入 SQLite，样本 ID 为 `{原图ID}_{尺寸}`。重复运行会跳过已完成样本；`--ids 3975` 或 `--limit 10` 可用于小规模验证。没有 MPS GPU 时脚本会退出，不会退回 CPU。source 原图使用硬链接，不会为四种尺寸复制四份原图。队列通过 SQLite 分页查询和前端虚拟列表浏览，可筛选尺寸并记住上次选择；每行的序号对应当前筛选结果中的位置。

## 数据结构

标注结果位于 `webui/data/`，此目录被 Git 忽略：

```text
data/
  sources/{id}.png         source 原图
  annotation.sqlite3      样本、像素索引、其余 PNG、元数据和审核记录
```

SQLite 中的 `samples` 表保存压缩的像素索引和可查询的状态列，`images` 表保存预测图、修正图和 edit mask 的 PNG 二进制数据，`metadata` 表保存元数据，`assets` 表保存辅助预览。`edit_mask` 比较的是导入时映射到调色板的基线与当前修正结果。网页的大块像素数据通过二进制格式传输；小型分页列表仍使用 JSON。

已有旧版 `indices/`、`predictions/`、`corrected/`、`edit_masks/`、`meta/` 和 `reviews/` 目录时，先将整个 `data/` 备份到项目外，再运行 `python3 ../scripts/migrate_annotation_sqlite.py`。脚本会校验记录数量和 SQLite 完整性，再将临时数据库移到 `data/annotation.sqlite3`。确认页面和脚本均可读取后，可移走旧目录。

## 本地 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/annotation/samples?offset=0&limit=100&q=3975&size=24` | 按 ID 和尺寸分页查询样本，返回 `items`、`total`、`all_total`、`completed`、`offset`、`limit` |
| POST | `/api/annotation/samples` | 导入原图，可选 ID 和预测图；缺少预测图时自动生成四种尺寸。网页使用二进制帧，旧 JSON base64 请求仍兼容 |
| GET | `/api/annotation/samples/:id?format=binary` | 高效读取像素索引和元数据；省略 `format` 仍返回 JSON |
| GET | `/api/annotation/samples/:id/image?kind=sources` | 读取图片；`kind` 也可为 `predictions`、`corrected`、`edit_masks` |
| POST | `/api/annotation/samples/:id/save` | 保存像素索引；网页使用二进制帧，旧 JSON 请求仍兼容 |
| GET | `/api/annotation/palette` | 固定色板 |

前端组件集中在 `src/app/annotate/page.vue`；SQLite 存储在 `server/annotation-db.mjs`，API 与 PNG 编解码在 `server/annotation-api.mjs`。开发模式由 Vite 中间件挂载，构建后由 `server/start.mjs` 提供静态页面与同一 API。
