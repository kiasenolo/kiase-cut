// @filter 映射範圍
// @category 轉換器
// @description 節點用：照 Blender 的「映射範圍」節點：輸入是數值（圖進來就是黑白的明度，透明處是 0），從 [來源最小, 來源最大] 重新對應到 [目標最小, 目標最大]，結果是黑白的圖
// @source 數值
// @param mode menu 線性 "線性|階梯|平滑|更平滑" "插值"
// @param from_min float 0 -1000 1000 "來源最小"
// @param from_max float 1 -1000 1000 "來源最大"
// @param to_min float 0 -1000 1000 "目標最小"
// @param to_max float 1 -1000 1000 "目標最大"
// @param steps float 4 0 1000 "階梯數"
// @param clamp_on bool true "限制範圍"

float remap(float v) {
    float span = from_max - from_min;
    float t = span != 0.0 ? (v - from_min) / max(abs(span), 1e-30) * sign(span) : 0.0;
    if (clamp_on) t = clamp(t, 0.0, 1.0);
    if (mode == 1) t = floor(t * (steps + 1.0)) / max(steps, 1e-6);          // (Blender: steps)
    else if (mode == 2) { t = clamp(t, 0.0, 1.0); t = t * t * (3.0 - 2.0 * t); }
    else if (mode == 3) { t = clamp(t, 0.0, 1.0); t = t * t * t * (t * (t * 6.0 - 15.0) + 10.0); }
    float r = to_min + t * (to_max - to_min);
    if (clamp_on) r = clamp(r, min(to_min, to_max), max(to_min, to_max));
    return r;
}

vec4 effect(vec2 uv) {
    float a = dot(src(uv).rgb, vec3(0.2126, 0.7152, 0.0722));        // (a float input: the picture's brightness over black)
    return vec4(vec3(remap(a)), 1.0);
}
