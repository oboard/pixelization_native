# 可复用的平涂标注命令

配置按原图编号保存，四种逻辑尺寸共用。第一种原图颜色是透明背景；
每种颜色通过互斥分类映射到 MARD 索引，避免颜色阈值重叠产生杂色。

```sh
node scripts/pixel_annotate.mjs profile-set 498 --colors '#FFFFFF:-1,#FA9AFD:244,#FFFF00:246,#000000:189' --ink 3 --enclosed-white 184 --coverage 0.44 --ink-coverage 0.2
node scripts/pixel_annotate.mjs profile-patch 498 --rect 212,273,289,302 --from 184 --color 244
node scripts/pixel_annotate.mjs recipe-preview 498 --sizes 52,78,104
# 逐张查看预览，再提交：
node scripts/pixel_annotate.mjs recipe-apply 498 --sizes 52,78,104
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

小尺寸常需单独设计，不能仅凭大尺寸的效果批量提交。每张图仍需检查
主体比例、轮廓连续性、孤立杂点、眼睛和鼻子等关键细节。
