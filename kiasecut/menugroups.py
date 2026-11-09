"""Menu parameters with many choices (a Math node's 運算, a Mix node's 混合模式) are shown in groups side by side, as Blender's are:
of(items) -> [(title, [choice, ...]), ...] when the choices are one of the sets known here, else None (a plain menu)."""

TABLES = (
    (("函數", ["相加", "相減", "相乘", "相除", "乘加", "次方", "對數", "平方根", "平方根倒數", "絕對值", "指數"]),         # Math
     ("比較", ["最小", "最大", "小於", "大於", "正負號", "比較", "平滑最小", "平滑最大"]),
     ("取整", ["四捨五入", "向下取整", "向上取整", "截斷", "小數部分", "截斷取餘", "向下取餘", "迴繞", "對齊", "來回"]),
     ("三角函數", ["正弦", "餘弦", "正切", "反正弦", "反餘弦", "反正切", "反正切2", "雙曲正弦", "雙曲餘弦", "雙曲正切"]),
     ("轉換", ["轉弧度", "轉角度"])),
    (("一般", ["混合"]),                                                                                             # Mix
     ("變暗", ["變暗", "相乘", "加深顏色"]),
     ("變亮", ["變亮", "濾色", "加亮顏色", "相加"]),
     ("對比", ["疊加", "柔光", "線性光"]),
     ("反相", ["差異", "排除", "相減", "相除"]),
     ("分量", ["色相", "飽和度", "顏色", "明度"])),
    (("基本", ["相加", "相減", "相乘", "相除", "乘加"]),                                                              # Vector Math
     ("向量", ["外積", "投影", "反射", "折射", "朝向", "點積", "距離", "長度", "縮放", "正規化"]),
     ("數值", ["絕對值", "次方", "正負號", "最小", "最大"]),
     ("取整", ["四捨五入", "向下取整", "向上取整", "小數部分", "取餘", "迴繞", "對齊"]),
     ("三角函數", ["正弦", "餘弦", "正切"])),
    (("一般", ["正常"]),                                                                                             # a clip's 混合模式
     ("變暗", ["變暗", "正片疊底", "顏色加深"]),
     ("變亮", ["變亮", "濾色", "顏色減淡", "相加"]),
     ("對比", ["疊加", "柔光", "強光"]),
     ("反相", ["差值", "排除"])),
    (("一般", ["穿透", "正常"]),                                                                                      # ... of a group (穿透 too)
     ("變暗", ["變暗", "正片疊底", "顏色加深"]),
     ("變亮", ["變亮", "濾色", "顏色減淡", "相加"]),
     ("對比", ["疊加", "柔光", "強光"]),
     ("反相", ["差值", "排除"])),
)


def of(items):
    """The groups of a menu's choices, or None: the choices must be exactly those of one table (the same names in any order)."""
    names = list(items)
    for table in TABLES:
        flat = [n for _t, group in table for n in group]
        if len(flat) == len(names) and set(flat) == set(names):
            return [(title, list(group)) for title, group in table]
    return None
