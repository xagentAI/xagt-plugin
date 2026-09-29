"""通过 UNO 连接已在监听的 LibreOffice：更新目录域、回存 docx、导出 PDF。

用法（先启动监听）：
  soffice --headless --invisible --norestore "--accept=socket,host=localhost,port=2002;urp;"
  "C:\\Program Files\\LibreOffice\\program\\python.exe" scripts/lo_update_and_export.py <docx> <pdf>
"""

import sys
import time
from pathlib import Path

import uno
from com.sun.star.beans import PropertyValue


def prop(name: str, value):
    p = PropertyValue()
    p.Name = name
    p.Value = value
    return p


def main() -> None:
    docx_path = Path(sys.argv[1]).resolve()
    pdf_path = Path(sys.argv[2]).resolve()

    local_ctx = uno.getComponentContext()
    resolver = local_ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local_ctx
    )
    ctx = None
    for _ in range(30):
        try:
            ctx = resolver.resolve(
                "uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext"
            )
            break
        except Exception:
            time.sleep(1)
    if ctx is None:
        raise RuntimeError("无法连接 LibreOffice 监听端口")

    desktop = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", ctx
    )
    doc = desktop.loadComponentFromURL(
        uno.systemPathToFileUrl(str(docx_path)), "_blank", 0,
        (prop("Hidden", True),),
    )

    # 更新全部目录/索引
    indexes = doc.getDocumentIndexes()
    for i in range(indexes.getCount()):
        indexes.getByIndex(i).update()
    # 更新普通域（页码等）
    doc.getTextFields().refresh()

    doc.store()  # 回存 docx（目录缓存随之写入）
    doc.storeToURL(
        uno.systemPathToFileUrl(str(pdf_path)),
        (prop("FilterName", "writer_pdf_Export"),),
    )
    doc.close(False)
    print("indexes updated; docx stored; pdf exported")


if __name__ == "__main__":
    main()
