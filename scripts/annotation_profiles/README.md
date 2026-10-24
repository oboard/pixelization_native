# 可复用的平涂标注命令

配置按原图编号保存，四种逻辑尺寸共用。第一种原图颜色是透明背景；
每种颜色通过互斥分类映射到 MARD 索引，避免颜色阈值重叠产生杂色。

```sh
node packages/pixel-annotate/pixel_annotate.ts profile-set 498 --colors '#FFFFFF:-1,#FA9AFD:244,#FFFF00:246,#000000:189' --ink 3 --enclosed-white 184 --coverage 0.44 --ink-coverage 0.2
node packages/pixel-annotate/pixel_annotate.ts profile-patch 498 --rect 212,273,289,302 --from 184 --color 244
node packages/pixel-annotate/pixel_annotate.ts recipe-preview 498 --sizes 52,78,104
# 逐张查看预览，再提交：
node packages/pixel-annotate/pixel_annotate.ts recipe-apply 498 --sizes 52,78,104
```

- `--ink` 是颜色列表中的位置（从 0 开始），不是 MARD 索引。
- `--enclosed-white` 保留轮廓包围的白色区域，参数为 MARD 索引。
- `--symmetry` 对颜色覆盖率作左右平均，适合正面表情、对称图案。
- `--outline` 将主体边界统一为墨线色，适合需要连续黑边的图案。
- `profile-patch` 在 512×512 坐标框内替换指定索引，不影响其他颜色。
- `profile-stroke <序号> --points '145,218;226,199' --color 38 --width 3`
  添加按 512×512 原图坐标定义的折线。自动缩放到逻辑像素，最细一格，
  裁切到主体内部。可重复调用绘制叶脉、衣服缝线等细节。
- `profile-set` 会替换已有配置，包括局部修正；追加修正用 `profile-patch`。
- `profile-grid <序号> --size 24 --rows '<24 行字符，以 / 分隔>' --legend '.:-1,K:189,W:184,P:244,Y:246'`
  保存单独设计的 24×24 像素稿。每行必须 24 个字符；映射到固定色板，
  不影响 52、78、104 的参数。预览和提交仍使用 `recipe-preview` / `recipe-apply --sizes 24`。
- `profile-mirror 498 --size 24 --keep 13,1,21,6` 将手工稿左半边镜像到右半边，
  保留指定区域（逻辑像素坐标），适合正面角色与单侧蝴蝶结等装饰。
- `profile-ellipse 498 --rect 160,180,186,206 --color 189` 绘制规则圆点，
  坐标基于 512×512；可加 `--outline 189 --width 4` 绘制闭合领口等轮廓。
  小圆点采用偶数直径，避免三格圆变成十字形。
- `profile-region <序号> --points 'x,y;x,y;...' --color 144` 按主体轮廓填色；
  加 `--mask` 可限制主体区域。`profile-set --regions-only` 从透明画布开始，
  适合背景与皮肤接近、带纸纹或摄影噪声的图片。先定义头发、衣物等大区域，
  再叠加脸和手，最后用细线命令绘制表情。坐标仍基于 512×512 归一化原图。
- 配置改变后旧预览失效，必须重新预览。提交默认跳过已有标注，保存为待审核。

- `profile-fit 4236 --size 24 --padding 1` 裁掉手工 grid 的透明空白，
  按比例用最近邻放大并居中，保留指定像素边距；只处理指定尺寸。
- `profile-rays 567 --size 78 --center 264,256 --clear 177 --inner 204 --outer 254 --count 14 --width 10 --color 188`
  保留中心连通主体，清理外圈旧线，在指定半径之间均匀绘制放射线。
  中心、半径和线宽均为 512 坐标。适合太阳等图案，需预览检查主体是否被裁切。
- `profile-pop 422 --kind strokes` 撤销最后一项配置操作，
  可选 `strokes`、`patches`、`ellipses`、`regions`。

小尺寸常需单独设计，不能仅凭大尺寸的效果批量提交。每张图仍需检查
主体比例、轮廓连续性、孤立杂点、眼睛和鼻子等关键细节。

### 像素标签

`profile-label 11 --size 104 --text SCHOOLBUS --at 35,5 --clear 34,3,69,11 --background 4 --color 198`
用固定 3×5 字体重画英文标签，字符之间留一列空白。坐标是该尺寸的逻辑像素，
清理区域包含端点，文字必须完全放得进去。支持 A–Z 和空格；命令会转为大写。
用于车身、标牌等缩小后散成噪点的文字。小尺寸须选择足够短的标签或单独设计符号。
已有手工 grid 的尺寸需直接编辑像素稿，避免两套定义相互覆盖。

### 追加颜色映射

`profile-color 12 --rgb '#151515' --index 198` 在保留现有路径、局部修改和
尺寸配置的同时追加一个原图 RGB 原型，可把多个原图颜色映射到同一个色板索引。
例如带棕色头发的配置也要保留一个中性深色原型，避免纯黑瞳孔被中性灰色吸收。
已有手工 grid 不会因此自动改变；修改后需重新预览其他尺寸。

`profile-tune 15 --coverage 0.45 --ink-coverage 0.18` 保留配置中的路径、
局部修正和手工稿，调整主体覆盖率与黑线覆盖率。数值范围为大于 0 且不超过 1。
降低黑线阈值可修补细轮廓，但也可能让小尺寸五官挤在一起，必须分别检查。

`profile-threshold 16 --class 2 --coverage 0.18` 为某个原图 RGB 原型单独设置
覆盖阈值，适合灰色卷发边线等非黑色细线。`class` 是配置 `rgb` 列表的从 0
开始的序号，不是色板索引；背景类 0 不可覆盖。黑色 ink 仍在这些覆盖之后应用，
避免灰色边缘替换黑色五官。已有手工 grid 不受影响。
可加 `--rect 0,0,512,235` 将覆盖阈值限制在指定的 512 坐标区域，
例如只加强头发灰线而不改变嘴边的灰色抗锯齿。

`profile-stroke 17 --points '153,2;160,18;164,39;164,66;158,94;149,117' --color 4 --width 3 --extend`
允许沿路径补画当前透明区域，用于触角、绳索等缩小后消失的独立细线。
不加 `--extend` 时仍限制在已有不透明主体内；使用后需检查是否穿过其他角色。
