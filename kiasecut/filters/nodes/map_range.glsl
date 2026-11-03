// @filter 映射範圍
// @category 轉換器
// @description 節點用：照 Blender 的「映射範圍」節點：從 [來源最小, 來源最大] 重新對應到 [目標最小, 目標最大]。浮點：輸入是數值（圖進來就是黑白的明度，透明處是 0），結果是黑白的圖；向量：紅綠藍當 X、Y、Z，每個軸各自用自己的範圍（下面五個向量），結果保留圖的透明度
// @source 數值
// @param data_type menu 浮點 "浮點|向量" "資料型態"
// @param mode menu 線性 "線性|階梯|平滑|更平滑" "插值"
// @param from_min float 0 -1000 1000 "來源最小"
// @param from_max float 1 -1000 1000 "來源最大"
// @param to_min float 0 -1000 1000 "目標最小"
// @param to_max float 1 -1000 1000 "目標最大"
// @param steps float 4 0 1000 "階梯數"
// @param from_min_v vec3 0,0,0 -1000 1000 "來源最小（向量）"
// @param from_max_v vec3 1,1,1 -1000 1000 "來源最大（向量）"
// @param to_min_v vec3 0,0,0 -1000 1000 "目標最小（向量）"
// @param to_max_v vec3 1,1,1 -1000 1000 "目標最大（向量）"
// @param steps_v vec3 4,4,4 0 1000 "階梯數（向量）"
// @param clamp_on bool true "限制範圍"
// @show from_min data_type == 浮點
// @show from_max data_type == 浮點
// @show to_min data_type == 浮點
// @show to_max data_type == 浮點
// @show steps data_type == 浮點
// @show steps mode == 階梯
// @show from_min_v data_type == 向量
// @show from_max_v data_type == 向量
// @show to_min_v data_type == 向量
// @show to_max_v data_type == 向量
// @show steps_v data_type == 向量
// @show steps_v mode == 階梯

// Reimplementation of Blender's Map Range compositor node: its behaviour checked against Blender 5.2 (a comment below says where code was ported from Blender's shaders).
// Blender: https://github.com/blender/blender
// SPDX-FileCopyrightText: Blender Authors (original, GPL-2.0-or-later); KiaseCut
// SPDX-License-Identifier: GPL-3.0-or-later

float remap(float v, float from_min, float from_max, float to_min, float to_max, float steps) {
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
    if (data_type == 1) {                                                    // a vector: every axis on its own
        vec4 a = unpremultiply(src(uv));
        vec3 r = vec3(remap(a.r, from_min_v.x, from_max_v.x, to_min_v.x, to_max_v.x, steps_v.x),
                      remap(a.g, from_min_v.y, from_max_v.y, to_min_v.y, to_max_v.y, steps_v.y),
                      remap(a.b, from_min_v.z, from_max_v.z, to_min_v.z, to_max_v.z, steps_v.z));
        return premultiply(vec4(r, a.a));
    }
    float a = dot(src(uv).rgb, vec3(0.2126, 0.7152, 0.0722));        // (a float input: the picture's brightness over black)
    return vec4(vec3(remap(a, from_min, from_max, to_min, to_max, steps)), 1.0);
}
