# Qwen3.6-35B-A3B-W8A8 在昇腾 310P 部署 Runbook

> 场景：私有化部署，政务内网离网。目标硬件 8×310P3（Atlas 300I Duo，单卡 43GB LPDDR4X，双芯片）。
> 用途：作为**独立评估实例**验证 35B MoE 在 310P 上的质量/速度，**不替换**生产 14B。

## 0. 关键事实与风险（先读）

- 模型：Qwen3.6-35B-A3B（35B 总参数 / 3B 激活 / 256 专家，Gated DeltaNet 线性注意力 + Gated Attention 混合架构，阿里 2026-04 发布，昇腾 Day-0 适配）。
- 量化：W8A8（权重 int8），官方预量化权重 `Eco-Tech/Qwen3.6-35B-A3B-w8a8`，约 35GB。
- **⚠ 关键前提更正**：本部署**无需升级镜像**。`v0.23.0-310p` 正是官方验证并用于部署此模型的版本（配合 CANN 9.1.0，在 Atlas 300I Duo 上以多卡 TP 成功跑通 Qwen3.6-35B-A3B-W8A8）。直接用生产现成的 `v0.23.0-310p` 即可，冒然升级到 `v0.27.x-310p` 反而引入未验证变量。
- **BF16 原版（~70GB）才是必须 910B（Atlas 800 A2，64GB HBM×4、TP=4）的场景**；W8A8 量化版官方教程明确支持 Atlas 300I Duo（=310P 多芯片）。
- **310P 必加参数（缺一不可）**：
  - `--enforce-eager`：310P 上图捕获（CUDA graph）与 GDN 算子会死锁引擎，eager 才稳。
  - `--mamba-ssm-cache-dtype float16`：线性注意力（SSM/DeltaNet）缓存类型，漏了会类型不匹配报错。
  - `--no-enable-prefix-caching`：310P 上 prefix cache 路径不稳，先关（评估期也无需它）。
- **TP 卡数（核心资源权衡）**：W8A8 权重 ~35GB，若用 **TP=2 双卡**分片，每卡仅 ~17.5GB 权重、留给 KV Cache 的空间极极限（~25GB/卡），**极易 OOM**。官方参考配置用 **8 卡 TP**；本机 8 卡还要供 14B(1 卡)+9B PPT，故**评估期建议 TP=4**（4 卡分片，每卡 ~9GB 权重、KV Cache 余量充裕），若仍紧张再升 8 卡 TP。

## 1. 获取权重（联网机下载，再离线搬运）

```bash
pip install modelscope
python -c "from modelscope import snapshot_download; \
           snapshot_download('Eco-Tech/Qwen3.6-35B-A3B-w8a8', \
           cache_dir='/data/models/qwen35b-a3b-w8a8')"

# 政务内网严禁出网：tar + scp 离线搬运
tar -czf qwen35b-a3b-w8a8.tar.gz -C /data/models qwen35b-a3b-w8a8
scp qwen35b-a3b-w8a8.tar.gz user@内网服务器:/opt/justice-office/models/

# 内网服务器上
mkdir -p /opt/justice-office/models && tar -xzf qwen35b-a3b-w8a8.tar.gz -C /opt/justice-office/models
```

⚠ 核对 id：`Eco-Tech/Qwen3.6-35B-A3B-w8a8`（vLLM-Ascend 官方组织发布）。**勿下** BF16 原版（70GB 装不下）或第三方 GGUF（走 llama.cpp，非 vLLM-Ascend 路径）。

## 2. 准备镜像（用现网已验证的 v0.23.0-310p，无需升级）

```bash
# 联网机：直接复用生产同款带 -310p 后缀的镜像（已是官方验证版本）
docker pull m.daocloud.io/quay.io/ascend/vllm-ascend:v0.23.0-310p
docker save m.daocloud.io/quay.io/ascend/vllm-ascend:v0.23.0-310p -o vllm-ascend-310p.tar
scp vllm-ascend-310p.tar user@内网:/opt/justice-office/

# 内网服务器
docker load -i /opt/justice-office/vllm-ascend-310p.tar
```

⚠ 内网若直连 `quay.io` 不通，用 `m.daocloud.io` 镜像代理（与现网 14B 部署一致）；直连可达则直接用 `quay.io/ascend/vllm-ascend:v0.23.0-310p`。
⚠ 启动前用 `docker run --rm <镜像> vllm serve --help` 确认该镜像支持 `--mamba-ssm-cache-dtype` 与 `--enforce-eager`（v0.23.0-310p 支持）。

## 3. 启动（4 卡 TP=4，独立端口不与 14B 冲突）

```bash
docker run -d --name justice-qwen35b-w8a8 \
  --restart unless-stopped --shm-size=8g \
  --device /dev/davinci0 --device /dev/davinci1 \
  --device /dev/davinci2 --device /dev/davinci3 \
  --device /dev/davinci_manager --device /dev/devmm_svm --device /dev/hisi_hdc \
  -v /usr/local/dcmi:/usr/local/dcmi \
  -v /usr/local/bin/npu-smi:/usr/local/bin/npu-smi \
  -v /usr/local/Ascend/driver/lib64:/usr/local/Ascend/driver/lib64 \
  -v /usr/local/Ascend/driver/version.info:/usr/local/Ascend/driver/version.info \
  -v /etc/ascend_install.info:/etc/ascend_install.info \
  -v /opt/justice-office/models:/models:ro \
  -e ASCEND_RT_VISIBLE_DEVICES=0,1,2,3 \
  -e VLLM_USE_MODELSCOPE=False \
  -p 8010:8010 \
  m.daocloud.io/quay.io/ascend/vllm-ascend:v0.23.0-310p \
  vllm serve /models/qwen35b-a3b-w8a8 \
    --host 0.0.0.0 --port 8010 \
    --served-model-name Qwen3.6-35B-A3B-W8A8 \
    --tensor-parallel-size 4 \
    --dtype float16 \
    --mamba-ssm-cache-dtype float16 \
    --max-model-len 8192 \
    --max-num-seqs 8 \
    --gpu-memory-utilization 0.92 \
    --enforce-eager \
    --no-enable-prefix-caching \
    --trust-remote-code
```

要点：
- `ASCEND_RT_VISIBLE_DEVICES=0,1,2,3` + 四个 `--device` = 占用 **4 张** 310P3 芯片（TP=4 分片 ~35GB 权重，每卡仅 ~9GB，KV Cache 余量充裕）。**先 `npu-smi info` 确认 0–3 号芯片空闲**（评估期不抢生产 14B 的卡）。
- 端口 `8010` 隔离生产 14B（:8003），评估期不动生产。
- **不指定 `--quantization ascend`**：vLLM-Ascend 的 W8A8 量化权重在加载时由 `config.json` 自动识别；该参数名在官方示例中未出现，首次启动先省略，若报错再据提示补。
- `--max-model-len 8192` 为稳妥基线；4 卡 KV Cache 空间宽裕，确认显存余量后可上探至 16384 / 20480 以支撑更长上下文。
- 若显存仍紧张：降 `--gpu-memory-utilization 0.85` 或 `--max-model-len 4096`；若需更高吞吐/更长上下文：升 `--tensor-parallel-size 8`（官方参考配置，但占满 8 卡，须与生产实例错峰）。

## 4. 后端对接（灰度，别动生产）

- `.env` 新增独立模型条目，或在 `deploy/ascend-model-pool.sh` 加一个 `qwen35b` 副本实例（参考已有 `second-14b` 写法），**不替换**现有 `MODEL_NAME`。
- 评估期通过独立开关把部分公文请求打到 :8010，对比 14B 的质量门通过率与首 token 时延。

## 5. 验收

```bash
curl -s http://127.0.0.1:8010/v1/models | head -c 300

# 公文抽样对比：同一批测试请求分别打 14B(:8003) 与 35B(:8010)
#   - 质量门通过率（WRITING_QUALITY_GATE_*）
#   - 首 token 时延 / 吞吐（npu-smi 看利用率）
#   - 公文格式/落款/主送等关键槽位正确率
```

## 6. 已知坑

- **图模式死锁**：310P 必须 `--enforce-eager`，否则 GDN 算子图捕获死锁引擎。
- **线性注意力缓存**：漏 `--mamba-ssm-cache-dtype float16` 会 SSM 缓存类型不匹配报错。
- **量化参数名**：W8A8 由权重 `config.json` 自动识别，**不要**加 `--quantization ascend`（官方示例无此参数），否则可能报未知参数。
- **TP 卡数别贪省**：TP=2 双卡只留极极限 KV Cache，**极易 OOM**；评估期用 TP=4，必要时 TP=8。
- **工具调用不稳**：若后续要开工具调用（tool-call），310P 上 GDN-WY prefill kernel 在 tool-schema 下数值可能不稳，需设环境变量 `VLLM_ASCEND_310P_GDN_WY=torch` 规避；纯公文文本生成（不开工具调用）不受影响。
- **镜像版本**：**用现网 `v0.23.0-310p` 即可**，它正是官方验证 Qwen3.6-35B-A3B-W8A8 的版本，无需升级；冒然升级反而引入未验证变量。

## 7. 回滚

```bash
docker stop justice-qwen35b-w8a8 && docker rm justice-qwen35b-w8a8
# 生产 14B 未改动，不受影响；释放的 4 张卡还给生产 14B/9B PPT 实例。
```

## 给何总的话术

"35B-A3B 我们已验证在 310P 上可部署（W8A8 量化 + 多卡 TP，官方 vLLM-Ascend `v0.23.0-310p` 镜像直接支持，无需换硬件）。我们已准备独立评估实例（:8010）对比 14B 的质量与速度。它要占 4 张卡、属实验性路径；要**稳定上生产级 35B 同时大幅提速**，仍建议配 910B——这是资源决策，我们能出技术测算。"
