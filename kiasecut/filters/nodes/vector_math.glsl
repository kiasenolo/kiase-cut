// @filter 向量數學
// @category 向量
// @description 節點用：照 Blender 的「向量數學」節點：圖像的紅綠藍當成向量 (X, Y, Z)，和 B、C（沒接圖就用下面的向量）做運算。點積、距離、長度的結果從「數值」輸出拿（灰階圖），其他從「向量」輸出拿
// @source A
// @input b "B"
// @input c "C"
// @output vector "向量"
// @output value "數值"
// @param op menu 相加 "相加|相減|相乘|相除|乘加|外積|投影|反射|折射|朝向|點積|距離|長度|縮放|正規化|絕對值|最小|最大|向下取整|向上取整|小數部分|取餘|迴繞|對齊|正弦|餘弦|正切" "運算"
// @param vector_b vec3 0,0,0 -1000 1000 "B 的向量"
// @param vector_c vec3 0,0,0 -1000 1000 "C 的向量"
// @param vec_scale float 1 -1000 1000 "縮放 / 折射率"
// @show b op != 長度|縮放|正規化|絕對值|向下取整|向上取整|小數部分|正弦|餘弦|正切
// @show vector_b op != 長度|縮放|正規化|絕對值|向下取整|向上取整|小數部分|正弦|餘弦|正切
// @show c op == 乘加|朝向
// @show vector_c op == 乘加|朝向
// @show vec_scale op == 折射|縮放

vec3 safe_div(vec3 a, vec3 b) { return mix(vec3(0.0), a / max(abs(b), vec3(1e-30)) * sign(b), notEqual(b, vec3(0.0))); }
vec3 safe_norm(vec3 a) { float l = length(a); return l > 0.0 ? a / l : vec3(0.0); }

// the vector result and the number result of operation op
void calc(vec3 a, vec3 b, vec3 c, out vec3 v, out float f) {
    v = vec3(0.0); f = 0.0;
    if (op == 0) v = a + b;
    else if (op == 1) v = a - b;
    else if (op == 2) v = a * b;
    else if (op == 3) v = safe_div(a, b);
    else if (op == 4) v = a * b + c;
    else if (op == 5) v = cross(a, b);
    else if (op == 6) v = dot(b, b) > 0.0 ? dot(a, b) / dot(b, b) * b : vec3(0.0);
    else if (op == 7) v = reflect(a, safe_norm(b));
    else if (op == 8) v = refract(a, safe_norm(b), vec_scale);
    else if (op == 9) v = faceforward(a, b, c);
    else if (op == 10) f = dot(a, b);
    else if (op == 11) f = distance(a, b);
    else if (op == 12) f = length(a);
    else if (op == 13) v = a * vec_scale;
    else if (op == 14) v = safe_norm(a);
    else if (op == 15) v = abs(a);
    else if (op == 16) v = min(a, b);
    else if (op == 17) v = max(a, b);
    else if (op == 18) v = floor(a);
    else if (op == 19) v = ceil(a);
    else if (op == 20) v = a - floor(a);
    else if (op == 21) v = mix(vec3(0.0), a - b * trunc(a / max(abs(b), vec3(1e-30)) * sign(b)), notEqual(b, vec3(0.0)));
    else if (op == 22) {
        vec3 range = b - c;
        v = mix(c, a - range * floor((a - c) / max(abs(range), vec3(1e-30)) * sign(range)), notEqual(range, vec3(0.0)));
    }
    else if (op == 23) v = mix(vec3(0.0), floor(a / max(abs(b), vec3(1e-30)) * sign(b)) * b, notEqual(b, vec3(0.0)));
    else if (op == 24) v = sin(a);
    else if (op == 25) v = cos(a);
    else v = tan(a);
}

vec4 effect(vec2 uv) {
    vec4 a = unpremultiply(src(uv)), b = unpremultiply(input_b(uv)), c = unpremultiply(input_c(uv));
    vec3 v;
    float f;
    calc(a.rgb, b.a > 0.0 ? b.rgb : vector_b, c.a > 0.0 ? c.rgb : vector_c, v, f);
    if (output_index == 1) return vec4(vec3(f), 1.0);
    return premultiply(vec4(v, a.a));
}
