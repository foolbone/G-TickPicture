PP-OCRv6 端侧模型目录（P4 诉求 4）
====================================

本目录需要三个文件才能启用「增强识别」：

    det.onnx   文本检测  PP-OCRv6_small_det   9.4 MB
    rec.onnx   文本识别  PP-OCRv6_small_rec  20.2 MB
    keys.txt   识别字典  18708 行             73 KB


── 怎么拿到它们 ──────────────────────────────────────────────

    # 先看现状（会校验 sha256 和字典行数）
    powershell -File tools\fetch_ppocr_model.ps1 -Mode check

    # 下载（从 ModelScope，带 sha256 校验 + 自动生成 keys.txt）
    powershell -File tools\fetch_ppocr_model.ps1 -Mode fetch

    # 清空重来
    powershell -File tools\fetch_ppocr_model.ps1 -Mode clean

来源：ModelScope 上的官方 ONNX 仓库
    PaddlePaddle/PP-OCRv6_small_det_onnx
    PaddlePaddle/PP-OCRv6_small_rec_onnx

⚠️ huggingface.co 在国内多数网络不通（DNS 会被解析到错误 IP），
   所以脚本走 ModelScope。**官方发布的是 Paddle 推理格式**
   （inference.json + inference.pdiparams，Paddle 3.0 的 PIR 格式，
    没有 .pdmodel），不是 .onnx —— 上面这两个仓库是官方已经转好的
   ONNX 版本，因此**不需要 paddle2onnx**，直接下载即可。


── 为什么这些文件不在仓库里 ──────────────────────────────────
30 MB 二进制不该进版本控制，已在 app/.gitignore 里排除。


── 缺文件会怎样 ──────────────────────────────────────────────
**编译照常通过，运行期自动回退标准识别（ML Kit）。**

刻意为之：现场不能因为一个可选的增强功能没装就卡住。
回退逻辑见 lib/domain/ocr/ocr_engine_factory.dart，
原生侧见 kotlin/.../ppocr/OnnxPpOcrEngine.kt 的 create()。


── 前处理参数来自模型自带的 inference.yml，不要凭记忆改 ──────

  det:  BGR 通道序 + (x/255 - [0.485,0.456,0.406]) / [0.229,0.224,0.225]
        后处理 DBPostProcess：thresh 0.2 / box_thresh 0.45 / unclip 1.4
  rec:  BGR 通道序 + (x/255 - 0.5) / 0.5     <- 与 det **不是**一套
        输入固定 [3, 48, 320]，右侧补 0.0（= 中灰，不是黑边）

实测签名（用 tools 里的 ONNX 探针读出）：
  det  输入 x [N,3,H,W]          输出 fetch_name_0 [N,1,dH,dW]   概率图
  rec  输入 x [N,3,48,W]         输出 fetch_name_0 [N,T,18710]

  18710 = 1 个 CTC blank + 18708 个字典字符 + 1 个半角空格。
  这个数对不上就说明字典和模型版本不匹配 —— create() 会用 ONNX 输出
  维度反查，不一致直接返回 null 回退 ML Kit，绝不输出错字。


── 字典下标布局（错一位就是整片乱码，而且不报错）──────────────

  下标 0        -> CTC blank（不发字符）
  下标 1..18708 -> keys.txt 第 1..18708 行
  下标 18709    -> 半角空格

⚠️ 第 1748 条是 U+3000 全角空格「　」。读文件时**不能用 trim()**
   （Kotlin 的 trim 和 .NET 的 Trim 都会剥掉 Unicode 空白，
     把这条读成空串，后面 17000+ 个字符的下标整体前移）。
   只能用 trimEnd('\r','\n') / PowerShell 里只用 Substring。
