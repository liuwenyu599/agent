#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部署后一键出样稿验证：PPT 图示（MCP 优先 / 多用图 / 导出可编辑 / 商业级样式）。

验证目标（对应本次改动的四大方向）：
  1. MCP 上位主引擎  -> 统计 outline 里 blocks.diagram_engine == "mcp" 的页数
  2. 多用图          -> 统计有 drawio_xml 的页数（对比之前「9 页仅 1 图」）
  3. 导出仍可编辑    -> /drawio 端点返回可解析的 mxfile（每页 diagram 合法）
  4. 商业级样式落地  -> 下载 pptx，解析 XML 统计 阴影/圆角/渐变/粗连线 是否真的画进文件

==================================================================
重要（部署铁律）：
  - 生产 API 端口默认 8001，但 127.0.0.1:8001 在容器里是 loopback 陷阱；
    在服务器「本机」跑可以用 127.0.0.1:8001，在别的机器跑必须填宿主 LAN IP。
  - 本脚本只验证「已部署且在线」的环境。代码改动需要先 push -> 重建镜像 -> up -d，
    只改宿主机 + restart 看不到新效果（镜像 COPY server/ 固化了代码）。
  - 若部署环境没配 DRAWIO_MCP_URL（或 MCP 超时/校验不合格），路由会回退 Graphviz，
    此时 diagram_engine 会是 "graphviz" 而非 "mcp" —— 这不算 bug，是正常兜底。
==================================================================

用法：
  export PPT_API_BASE="http://<宿主LAN_IP>:8001"   # 见上方铁律
  export PPT_USER="admin"
  export PPT_PASSWORD="******"
  # 或者已有 token 直接给：
  export PPT_API_TOKEN="eyJ..."

  python3 deploy/verify_ppt_sample.py
  python3 deploy/verify_ppt_sample.py --topic "社区矫正安置帮教工作流程与三级组织架构及近三年帮扶数据对比" --slide-count 9
  python3 deploy/verify_ppt_sample.py --out-dir /tmp/ppt_sample
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional, Tuple

MAIN_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PPT_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"

# 2pt = 25400 EMU；1.6pt（节点边框默认）= 20320 EMU。用于判断「粗连线」。
THICK_LINE_EMU = 25400


# --------------------------------------------------------------------------- #
# 极简 HTTP 客户端（仅用标准库，零第三方依赖）
# --------------------------------------------------------------------------- #
def _request(method: str, url: str, token: Optional[str], body: Optional[dict],
             timeout: int, binary: bool) -> Tuple[int, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:  # 服务器返回 4xx/5xx
        detail = exc.read().decode("utf-8", "ignore")[:500]
        return exc.code, detail
    except Exception as exc:  # 连接/超时/解析等
        return -1, f"{type(exc).__name__}: {exc}"
    if binary:
        return 200, raw
    text = raw.decode("utf-8", "ignore")
    try:
        return 200, json.loads(text)
    except json.JSONDecodeError:
        return 200, text


def api_json(method: str, base: str, path: str, token: str, body: Optional[dict] = None,
             timeout: int = 60) -> Tuple[int, Any]:
    return _request(method, f"{base}{path}", token, body, timeout, binary=False)


def api_binary(method: str, base: str, path: str, token: str,
               timeout: int = 120) -> Tuple[int, Any]:
    return _request(method, f"{base}{path}", token, None, timeout, binary=True)


# --------------------------------------------------------------------------- #
# 业务步骤
# --------------------------------------------------------------------------- #
def login(base: str, user: str, password: str) -> Tuple[int, str]:
    code, resp = api_json("POST", base, "/api/v1/auth/login", "",
                          body={"username": user, "password": password}, timeout=30)
    if code != 200 or not isinstance(resp, dict):
        return code, f"登录失败（HTTP {code}）：{resp}"
    token = resp.get("access_token")
    if not token:
        return code, f"登录响应缺少 access_token：{resp}"
    return 200, token


def make_outline(base: str, token: str, topic: str, slide_count: int) -> Tuple[int, dict]:
    body = {
        "source_type": "topic",
        "topic": topic,
        "audience": "司法所工作人员",
        "scene": "业务培训",
        "slide_count": slide_count,
    }
    # 同步路由，但模型调用可能较慢，给足超时
    return api_json("POST", base, "/api/v1/ppt/outline", token, body=body, timeout=300)


def generate(base: str, token: str, doc_id: str) -> Tuple[int, Any]:
    # /generate 是同步渲染落盘（会真实调用 MCP/Graphviz + 渲染器），耗时较长
    return api_json("POST", base, "/api/v1/ppt/generate", token,
                   body={"doc_id": doc_id}, timeout=600)


def get_document(base: str, token: str, doc_id: str) -> Tuple[int, dict]:
    return api_json("GET", base, f"/api/v1/ppt/documents/{doc_id}", token, timeout=60)


def download_pptx(base: str, token: str, doc_id: str, out_path: str) -> Tuple[int, str]:
    code, data = api_binary("GET", base, f"/api/v1/ppt/documents/{doc_id}/download",
                            token, timeout=180)
    if code != 200 or not isinstance(data, (bytes, bytearray)):
        return code, f"下载 PPTX 失败（HTTP {code}）：{data}"
    with open(out_path, "wb") as fh:
        fh.write(data)
    return 200, out_path


def download_drawio(base: str, token: str, doc_id: str, out_path: str) -> Tuple[int, str]:
    code, data = api_binary("GET", base, f"/api/v1/ppt/documents/{doc_id}/drawio",
                            token, timeout=120)
    if code != 200 or not isinstance(data, (bytes, bytearray)):
        # 400 表示「这份演示文稿没有可下载的 Draw.io 图示」——即没有任何图示页
        if code == 400:
            return 400, "无图示页（drawio 导出为空，符合预期当且仅当没有 process/data 页）"
        return code, f"下载 drawio 失败（HTTP {code}）：{data}"
    with open(out_path, "wb") as fh:
        fh.write(data)
    return 200, out_path


# --------------------------------------------------------------------------- #
# 解析与统计
# --------------------------------------------------------------------------- #
def analyze_outline(outline: dict) -> Dict[str, Any]:
    slides = (outline or {}).get("slides") or []
    engine_counter: Dict[str, int] = {}
    diagram_pages = 0
    type_counter: Dict[str, int] = {}
    for slide in slides:
        blocks = slide.get("blocks") or {}
        engine = blocks.get("diagram_engine")
        if engine:
            engine_counter[engine] = engine_counter.get(engine, 0) + 1
        if blocks.get("drawio_xml"):
            diagram_pages += 1
        t = slide.get("type") or blocks.get("drawio_kind") or "(无)"
        type_counter[t] = type_counter.get(t, 0) + 1
    return {
        "total_slides": len(slides),
        "diagram_pages": diagram_pages,
        "engine_counter": engine_counter,
        "type_counter": type_counter,
    }


def analyze_drawio(path: str) -> Dict[str, Any]:
    try:
        tree = ET.parse(path)
    except Exception as exc:
        return {"ok": False, "error": f"drawio 文件无法解析：{exc}"}
    root = tree.getroot()
    diagrams = root.findall("{http://www.w3.org/1999/xhtml}diagram") \
        if root.tag.endswith("mxfile") else []
    # mxfile 默认无命名空间
    if not diagrams and root.tag == "mxfile":
        diagrams = root.findall("diagram")
    valid = 0
    for d in diagrams:
        model = d.find("mxGraphModel")
        if model is not None and model.find("root") is not None:
            valid += 1
    return {"ok": True, "pages": len(diagrams), "valid_pages": valid}


def _spPr_props(spPr) -> Dict[str, Any]:
    props = {"shadow": False, "round_rect": False, "grad": False, "line_w": 0}
    if spPr is None:
        return props
    if spPr.find(f"{{{MAIN_NS}}}effectLst/{{{MAIN_NS}}}outerShdw") is not None:
        props["shadow"] = True
    pg = spPr.find(f"{{{MAIN_NS}}}prstGeom")
    if pg is not None and pg.get("prst") == "roundRect":
        props["round_rect"] = True
    if spPr.find(f"{{{MAIN_NS}}}gradFill") is not None:
        props["grad"] = True
    ln = spPr.find(f"{{{MAIN_NS}}}ln")
    if ln is not None and ln.get("w"):
        try:
            props["line_w"] = int(ln.get("w"))
        except ValueError:
            props["line_w"] = 0
    return props


def analyze_pptx(path: str) -> Dict[str, Any]:
    shadow = round_rect = grad = thick_conn = thick_shape = 0
    slides = 0
    with zipfile.ZipFile(path) as zf:
        slide_names = sorted(
            [n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)],
            key=lambda s: int(re.search(r"(\d+)", s).group(1)),
        )
        slides = len(slide_names)
        for name in slide_names:
            root = ET.fromstring(zf.read(name))
            # 形状 p:sp，连线 p:cxnSp
            for tag in ("sp", "cxnSp"):
                for el in root.iter(f"{{{PPT_NS}}}{tag}"):
                    spPr = el.find(f"{{{PPT_NS}}}spPr")
                    # 实际 spPr 在 drawinml/main 命名空间
                    if spPr is None:
                        spPr = el.find(f"{{{MAIN_NS}}}spPr")
                    props = _spPr_props(spPr)
                    if props["shadow"]:
                        shadow += 1
                    if props["round_rect"]:
                        round_rect += 1
                    if props["grad"]:
                        grad += 1
                    if props["line_w"] >= THICK_LINE_EMU:
                        if tag == "cxnSp":
                            thick_conn += 1
                        else:
                            thick_shape += 1
    return {
        "slides": slides,
        "shadow_shapes": shadow,
        "round_rect_shapes": round_rect,
        "gradient_shapes": grad,
        "thick_connectors": thick_conn,
        "thick_shape_borders": thick_shape,
    }


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def print_report(oid: dict, dio: dict, pptx: dict) -> None:
    print("\n" + "=" * 64)
    print("PPT 图示样稿验证报告")
    print("=" * 64)

    print("\n[1] 多用图 / 引擎分布（来自 outline.blocks.diagram_engine）")
    print(f"    总页数           : {oid.get('total_slides')}")
    print(f"    含图示的页数     : {oid.get('diagram_pages')}  "
          f"（之前基线：9 页仅 1 图）")
    print(f"    引擎分布         : {oid.get('engine_counter') or '{}'}")
    if oid.get("engine_counter", {}).get("mcp"):
        print("    -> MCP 已上位主引擎 ✅")
    elif oid.get("engine_counter", {}).get("graphviz"):
        print("    -> 当前走 Graphviz 兜底（MCP 未命中：可能未配 DRAWIO_MCP_URL / 超时 / 校验不合格）")
    else:
        print("    -> 没有任何图示引擎产出（全部为纯文字 content 页，检查大纲 Prompt 是否生效）")

    print("\n[2] 导出仍可编辑（drawio 端点）")
    if dio.get("ok"):
        print(f"    可编辑图示页数   : {dio.get('valid_pages')}/{dio.get('pages')}  "
              f"（mxfile 合法 ✅）" if dio.get("valid_pages") else
              f"    导出为空（无图示页）")
    else:
        print(f"    {dio.get('error')}")

    print("\n[3] 商业级样式落地（解析样稿 PPTX）")
    print(f"    幻灯片数         : {pptx.get('slides')}")
    print(f"    带阴影的形状     : {pptx.get('shadow_shapes')}  "
          f"{'✅ 阴影生效' if pptx.get('shadow_shapes') else '❌ 未见阴影'}")
    print(f"    圆角矩形         : {pptx.get('round_rect_shapes')}  "
          f"{'✅ 圆角生效' if pptx.get('round_rect_shapes') else '❌ 未见圆角'}")
    print(f"    渐变填充         : {pptx.get('gradient_shapes')}  "
          f"{'✅ 渐变生效' if pptx.get('gradient_shapes') else '❌ 未见渐变'}")
    print(f"    粗连线(>=2pt)    : {pptx.get('thick_connectors')}  "
          f"{'✅ 粗连线生效' if pptx.get('thick_connectors') else '❌ 未见粗连线'}")
    if pptx.get("thick_shape_borders"):
        print(f"    （另有 {pptx.get('thick_shape_borders')} 个形状边框 >=2pt）")

    print("\n" + "=" * 64)
    verdict = []
    if oid.get("diagram_pages", 0) >= 2:
        verdict.append("多用图 ✅")
    else:
        verdict.append("多用图 ⚠（图示页偏少，检查大纲 Prompt）")
    if dio.get("ok") and dio.get("valid_pages", 0) > 0:
        verdict.append("导出可编辑 ✅")
    if pptx.get("shadow_shapes") or pptx.get("round_rect_shapes") \
            or pptx.get("gradient_shapes") or pptx.get("thick_connectors"):
        verdict.append("商业级样式 ✅")
    else:
        verdict.append("商业级样式 ⚠（样式未落进 PPTX，检查 render_diagram）")
    print("结论: " + " | ".join(verdict))
    print("=" * 64)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description="PPT 图示样稿一键验证")
    parser.add_argument("--api-base", default=os.environ.get("PPT_API_BASE",
                                                            "http://127.0.0.1:8001"),
                        help="生产 API 基址，例如 http://<宿主LAN_IP>:8001")
    parser.add_argument("--user", default=os.environ.get("PPT_USER", ""))
    parser.add_argument("--password", default=os.environ.get("PPT_PASSWORD", ""))
    parser.add_argument("--token", default=os.environ.get("PPT_API_TOKEN", ""))
    parser.add_argument(
        "--topic",
        default="社区矫正安置帮教工作流程与各阶段职责，含区、街、社区三级组织架构，"
                "以及近三年帮扶人数、就业率的数值对比",
        help="用于触发图示/数据页的题材")
    parser.add_argument("--slide-count", type=int, default=9)
    parser.add_argument("--out-dir", default=os.environ.get("PPT_SAMPLE_DIR", "/tmp/ppt_sample"))
    args = parser.parse_args()

    print(f"[*] 目标 API : {args.api_base}")
    print(f"[*] 题材     : {args.topic}")
    if args.api_base.rstrip("/").endswith("127.0.0.1:8001") or "localhost" in args.api_base:
        print("[!] 警告：使用 127.0.0.1/localhost 仅在你「就在服务器本机」跑时才有效；"
              "跨机器请用宿主 LAN IP（见脚本顶部铁律）。")

    # 1. 鉴权
    token = args.token
    if not token:
        if not (args.user and args.password):
            print("[x] 未提供 token，也未提供 --user/--password，无法登录。退出。")
            return 2
        code, tok = login(args.api_base, args.user, args.password)
        if code != 200:
            print(f"[x] 登录失败：{tok}")
            return 1
        token = tok
        print("[*] 登录成功，已获取 token。")

    # 2. 生成大纲
    print("[*] 步骤1/5 生成大纲 ...")
    code, outline_resp = make_outline(args.api_base, token, args.topic, args.slide_count)
    if code != 200 or not isinstance(outline_resp, dict) or not outline_resp.get("doc_id"):
        print(f"[x] 大纲生成失败（HTTP {code}）：{outline_resp}")
        return 1
    doc_id = outline_resp["doc_id"]
    print(f"[*] 大纲已创建 doc_id={doc_id}")

    # 3. 同步渲染（真实调用 MCP/Graphviz + 渲染器）
    print("[*] 步骤2/5 同步渲染（可能耗时数十秒~数分钟）...")
    code, gen_resp = generate(args.api_base, token, doc_id)
    if code != 200:
        print(f"[x] 渲染失败（HTTP {code}）：{gen_resp}")
        return 1
    print(f"[*] 渲染完成：{gen_resp}")

    # 4. 取含 diagram_engine 的最终 outline
    print("[*] 步骤3/5 读取最终大纲（含 diagram_engine）...")
    code, doc_resp = get_document(args.api_base, token, doc_id)
    if code != 200 or not isinstance(doc_resp, dict):
        print(f"[x] 读取文档失败（HTTP {code}）：{doc_resp}")
        return 1
    oid = analyze_outline(doc_resp.get("outline") or outline_resp.get("outline"))

    # 5. 下载样稿 + drawio
    os.makedirs(args.out_dir, exist_ok=True)
    pptx_path = os.path.join(args.out_dir, f"sample_{doc_id}.pptx")
    dio_path = os.path.join(args.out_dir, f"sample_{doc_id}.drawio")

    print("[*] 步骤4/5 下载样稿 PPTX ...")
    code, pptx_msg = download_pptx(args.api_base, token, doc_id, pptx_path)
    if code != 200:
        print(f"[x] {pptx_msg}")
        return 1
    print(f"[*] 已保存：{pptx_path}")

    print("[*] 步骤5/5 下载可编辑 drawio ...")
    code, dio_msg = download_drawio(args.api_base, token, doc_id, dio_path)
    if code == 200:
        print(f"[*] 已保存：{dio_path}")
        dio = analyze_drawio(dio_path)
    elif code == 400:
        print(f"[*] {dio_msg}")
        dio = {"ok": True, "pages": 0, "valid_pages": 0}
    else:
        print(f"[!] {dio_msg}")
        dio = {"ok": False, "error": dio_msg}

    pptx = analyze_pptx(pptx_path)
    print_report(oid, dio, pptx)
    print(f"\n样稿文件：\n  PPTX : {pptx_path}\n  drawio: {dio_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
