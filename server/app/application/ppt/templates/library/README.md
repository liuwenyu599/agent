# 公共图库图片包（离线预置）

生产内网**严禁出网**，公共图库的图片只能离线预置：图片文件 + `manifest.json` 随仓库/镜像分发，
由种子命令导入 `ppt_library_images` 表。

## 目录结构

```
templates/library/
  manifest.json          # 清单（本目录）
  法治宣传/宪法宣传周.jpg  # 图片，按分类分目录（目录名随意，manifest 里写相对路径即可）
  党建/主题党日.jpg
```

## manifest.json 字段

```json
{
  "version": 1,
  "defaults": {
    "source": "本单位自有拍摄",
    "license_note": "内部授权，限本系统 PPT 使用"
  },
  "images": [
    {
      "file": "法治宣传/宪法宣传周.jpg",
      "name": "宪法宣传周",
      "caption": "司法所工作人员向群众发放宪法读本",
      "category": "法治宣传",
      "tags": ["宪法", "普法", "群众"],
      "source": "本单位自有拍摄",
      "license_note": "内部授权，限本系统 PPT 使用",
      "enabled": true
    }
  ]
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `file` | 是 | 相对本目录的图片路径，不允许 `..` 越界 |
| `name` | 是 | 展示名，**也是幂等键**（同名条目会被更新而不是重复插入） |
| `category` | 是 | 分类，建议取 manifest.categories 之一 |
| `source` | 是 | 来源登记（自有拍摄 / 采购授权 / 内部生成） |
| `license_note` | 是 | 授权说明，政务场景合规留痕 |
| `caption` | 否 | 说明，参与自动配图语义匹配；缺省用 name |
| `tags` | 否 | 标签数组，参与匹配 |
| `enabled` | 否 | 默认 true；false 表示入库但不上线 |

`source` / `license_note` 可写在 `defaults` 里统一给，条目内同名字段优先。

## 导入

### 先生成看图说明草稿

若已有本地图片目录，可在视觉模型部署并确认支持图片输入后运行：

```bash
# 草稿模式：逐张人工核对（enabled 默认 false）
python deploy/analyze_ppt_library_images.py pic --output pic/manifest.draft.json

# 采购图库批量入库：按分类归位、超限自动压缩、授权已确认后直接上架
python deploy/analyze_ppt_library_images.py pic \
  --copy-to server/app/application/ppt/templates/library \
  --output server/app/application/ppt/templates/library/manifest.json \
  --publish --source "采购授权" --license "内部授权，限本系统 PPT 使用"
```

工具会把缩小后的图片发给配置的 `VISION_MODEL_URL`，要求模型描述可见场景和动作，
不把 OCR 文字或文件名直接当成图片内容。它**不会修改原图**：

- 不带 `--copy-to`：`file` 保持原文件名，条目 `enabled` 为 false、来源与授权留空，
  须逐张核对后手动改为 true；
- 带 `--copy-to`：按识别出的分类复制到 `<DIR>/<分类>/`，超过 10MB 或 4000 万像素的
  自动转 JPEG 压缩（只写副本，原图不动）；
- 带 `--publish`：必须同时给 `--source` / `--license`，直接把 `enabled` 置 true，
  用于已确认授权的批量入库；不带则仍是待审草稿；
- `--resume` 复用清单里已识别的条目，`--limit` / `--only` / `--workers` 控制规模与并发。

若视觉模型不接受图片输入，识别失败会明确列出，说明保持空白，不会伪造标签。

审核后可用图片目录作为 `--base-dir`，把审核过的清单交给下面的种子命令。

```bash
# 预览（不落盘、不入库）
python deploy/seed_ppt_library_images.py --manifest pic/manifest.draft.json --base-dir pic --dry-run

# 正式导入（幂等，可反复运行）
python deploy/seed_ppt_library_images.py --manifest pic/manifest.draft.json --base-dir pic
```

- 同一张图重复导入 → `[跳过]`；
- 图片换了（sha256 变化）→ 覆盖文件并更新元数据 → `[更新]`；
- 缺少 `source` / `license_note`、图片损坏或格式不支持 → 该条记 `[错误]`，其余继续。

## 图片规格建议

- 单张 ≤ 800KB（硬上限 10MB），长边 ≤ 2400px，边长 ≥ 128px；
- 格式 JPEG / PNG / WEBP；系统自动生成 480px 缩略图；
- 禁止含可识别人脸、警徽/国徽使用不规范、涉密场所的图片；
- 首批建议 60~120 张，按 6 个分类均衡（每类 10~20 张）。
