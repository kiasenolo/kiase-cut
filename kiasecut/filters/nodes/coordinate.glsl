// @filter 座標
// @category 輸入
// @description 節點用：輸出座標當作圖（像 Blender 的紋理座標）：UV（紅＝X、綠＝Y）、只有 X 或 Y 的漸層、離中心的距離、繞中心的角度。接到別的節點的數字參數或遮罩，就能做漸層和放射效果
// @param mode menu UV "UV|X|Y|離中心的距離|角度" "輸出"
// @param center vec2 0.5,0.5 -2 3 "中心"

vec4 effect(vec2 uv) {
    vec2 d = (uv - center) * vec2(resolution.x / resolution.y, 1.0);
    if (mode == 0) return vec4(uv, 0.0, 1.0);
    if (mode == 1) return vec4(vec3(uv.x), 1.0);
    if (mode == 2) return vec4(vec3(uv.y), 1.0);
    if (mode == 3) return vec4(vec3(clamp(length(d) * 2.0, 0.0, 1.0)), 1.0);
    return vec4(vec3(atan(d.y, d.x) / 6.2831853 + 0.5), 1.0);
}
