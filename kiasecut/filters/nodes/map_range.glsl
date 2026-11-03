// @filter 映射範圍
// @category 轉換器
// @description 節點用：照 Blender 的「映射範圍」節點：把圖像每個通道從 [來源最小, 來源最大] 重新對應到 [目標最小, 目標最大]
// @source 數值
// @param mode menu 線性 "線性|階梯|平滑|更平滑" "插值"
// @param from_min float 0 -1000 1000 "來源最小"
// @param from_max float 1 -1000 1000 "來源最大"
// @param to_min float 0 -1000 1000 "目標最小"
// @param to_max float 1 -1000 1000 "目標最大"
// @param steps float 4 0 1000 "階梯數"
// @param clamp_on bool true "限制範圍"

vec3 remap(vec3 v) {
    vec3 span = vec3(from_max - from_min);
    vec3 t = mix(vec3(0.0), (v - from_min) / max(abs(span), vec3(1e-30)) * sign(span), notEqual(span, vec3(0.0)));
    if (clamp_on) t = clamp(t, 0.0, 1.0);
    if (mode == 1) t = floor(t * (steps + 1.0)) / max(steps, 1e-6);          // (Blender: steps)
    else if (mode == 2) { t = clamp(t, 0.0, 1.0); t = t * t * (3.0 - 2.0 * t); }
    else if (mode == 3) { t = clamp(t, 0.0, 1.0); t = t * t * t * (t * (t * 6.0 - 15.0) + 10.0); }
    vec3 r = to_min + t * (to_max - to_min);
    if (clamp_on) r = clamp(r, min(to_min, to_max), max(to_min, to_max));
    return r;
}

vec4 effect(vec2 uv) {
    vec4 a = unpremultiply(src(uv));
    return premultiply(vec4(remap(a.rgb), a.a));
}
