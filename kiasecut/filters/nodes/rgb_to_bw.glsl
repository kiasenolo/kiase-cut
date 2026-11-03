// @filter RGB 轉灰階
// @category 轉換器
// @description 節點用：照 Blender 的「RGB 轉 BW」：用明度（0.2126 R + 0.7152 G + 0.0722 B）變成灰階圖，透明度不變
// @source 顏色

vec4 effect(vec2 uv) {
    vec4 a = unpremultiply(src(uv));
    return premultiply(vec4(vec3(dot(a.rgb, vec3(0.2126, 0.7152, 0.0722))), a.a));
}
