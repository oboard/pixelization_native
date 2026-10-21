# 多节点标注 CLI

## 职责

- Server 管理原图、预测图、纠错图、mask、样本状态、审核历史、预览凭据和共享配方。
- CLI 通过 HTTP 读取和提交数据，在运行节点本地执行 JavaScript/Python 图像处理、生成预览和导出文件。
- CLI 和 Python 配方脚本均不打开 SQLite，不需要挂载 server 的 data 目录。
- `scripts/annotation_profiles` 保留在 server 的 Git 工作区中；CLI 的 `profile-*` 命令通过 API 修改该目录，多个节点读取同一份配方。

## 启动 server

在管理节点安装 webui 依赖、构建页面，然后启动现有 server：

```sh
cd webui
pnpm install
pnpm build
PIXEL_ANNOTATION_TOKEN=your-shared-token PORT=4173 pnpm start
```

数据位置仍可通过 `PIXEL_ANNOTATION_DATA_ROOT` 配置。
配方位置默认是项目的 `scripts/annotation_profiles`，可通过
`PIXEL_ANNOTATION_PROFILES_ROOT` 指定。已有数据和配方无需迁移。

## 启动 CLI

各执行节点需要项目代码、webui 的 pngjs 依赖，以及配方处理所需的 Python、NumPy、Pillow。
配置同一台 server：

```sh
export PIXEL_ANNOTATION_SERVER=http://management-host:4173
export PIXEL_ANNOTATION_TOKEN=your-shared-token
export PYTHON=/path/to/python

node scripts/pixel_annotate.mjs next --size 24
node scripts/pixel_annotate.mjs show 4236_52
node scripts/pixel_annotate.mjs edit 4236_52 --set 10,12:189
node scripts/pixel_annotate.mjs save 4236_52
node scripts/pixel_annotate.mjs recipe-preview 4236 --sizes 24,52,78,104
node scripts/pixel_annotate.mjs recipe-apply 4236 --sizes 24,52,78,104
node scripts/pixel_annotate.mjs export 4236_52
```

也可逐条传入 `--server URL`。默认地址是 `http://localhost:4173`。
现有命令、图片算法、颜色参数、`--force`、状态语义和输出路径保持兼容。
`--data-dir` 兼容保留为逻辑工作目录参数，不再指定服务端数据库位置。
导出写入当前 CLI 节点的 Downloads 或 `--output` 路径。
预览生成在执行节点的临时目录，配方预览 PNG 和指纹也会上传 server；
另一个节点使用相同代码和配方时可以继续 apply。

## 并发与提交

样本读取返回内容版本。CLI 在本地完成处理后，提交版本和资源包；
server 在同一个事务中校验版本并保存纠错图、mask、metadata、record。
中途出错会回滚，版本冲突返回 HTTP 409，不覆盖其他节点的修改。
共享配方更新也会校验版本。
收到冲突后重新读取、检查最新结果，再决定如何处理。
`next` 延续原有行为：优先返回被驳回样本，不会自动领取或锁定任务。
多个节点应选择不同样本或分配不同尺寸，避免重复计算。

管理接口支持可选的 `PIXEL_ANNOTATION_TOKEN`；设置后所有客户端请求必须携带
`Authorization: Bearer ...`。公网部署应使用 HTTPS。

## 客户端 API

路径前缀：`/api/annotation/client/`。

- `GET palette`：服务端权威调色板。
- `GET queue?size=&status=&q=&offset=&limit=`：分页队列和统计，limit 最大 200。
- `GET next?size=`：下一张候选。
- `GET profiles`：共享配方编号。
- `GET resources/:kind/:id`：base64 内容和 revision；kind 支持 sources、indices、meta、predictions、corrected、edit_masks、profiles。
- `PUT resources/profiles/:id`：`{content, expected_revision}`，新建时 revision 为 null。
- `PUT samples/:id`：`{expected_revision, writes:[{kind,content}]}`，按样本原子提交。
- `GET/PUT assets?name=reviews/recipes/...`：配方预览和指纹。

content 为 base64；revision 为服务端计算的 SHA-256，客户端不提交 SQL。

隔离数据验证命令（不访问现有标注）：

```sh
node --test scripts/tests/annotation-client.test.mjs
```
