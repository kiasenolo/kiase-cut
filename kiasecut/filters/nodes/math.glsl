// @filter 數學
// @category 轉換器
// @description 節點用：照 Blender 的「數學」節點：圖像的每個顏色通道當數值 A，和 B、C（沒接圖就用下面的數值）做運算，透明度不變。三角函數的角度是弧度
// @source A
// @input b "B"
// @input c "C"
// @param op menu 相加 "相加|相減|相乘|相除|乘加|次方|對數|平方根|平方根倒數|絕對值|指數|最小|最大|小於|大於|正負號|比較|平滑最小|平滑最大|四捨五入|向下取整|向上取整|截斷|小數部分|截斷取餘|向下取餘|迴繞|對齊|來回|正弦|餘弦|正切|反正弦|反餘弦|反正切|反正切2|雙曲正弦|雙曲餘弦|雙曲正切|轉弧度|轉角度" "運算"
// @param value float 0.5 -1000 1000 "B 的數值"
// @param value3 float 0.5 -1000 1000 "C 的數值"
// @param clamp_on bool false "限制在 0~1"

vec3 safe_div(vec3 a, vec3 b) { return mix(vec3(0.0), a / max(abs(b), vec3(1e-30)) * sign(b), notEqual(b, vec3(0.0))); }

vec3 power(vec3 a, vec3 b) {
    vec3 r = vec3(0.0);
    for (int i = 0; i < 3; i++) {
        if (a[i] >= 0.0) r[i] = pow(a[i], b[i]);
        else if (b[i] == floor(b[i])) r[i] = (mod(b[i], 2.0) == 0.0 ? 1.0 : -1.0) * pow(-a[i], b[i]);
    }
    return r;
}

vec3 smooth_min(vec3 a, vec3 b, vec3 c) {
    vec3 h = max(c - abs(a - b), 0.0) / max(c, vec3(1e-30));
    return mix(min(a, b), min(a, b) - h * h * h * c / 6.0, notEqual(c, vec3(0.0)));
}

vec3 smooth_max(vec3 a, vec3 b, vec3 c) {
    vec3 h = max(c - abs(a - b), 0.0) / max(c, vec3(1e-30));
    return mix(max(a, b), max(a, b) + h * h * h * c / 6.0, notEqual(c, vec3(0.0)));
}

vec3 calc(vec3 a, vec3 b, vec3 c) {
    if (op == 0) return a + b;
    if (op == 1) return a - b;
    if (op == 2) return a * b;
    if (op == 3) return safe_div(a, b);
    if (op == 4) return a * b + c;
    if (op == 5) return power(a, b);
    if (op == 6) return mix(vec3(0.0), log(max(a, vec3(1e-30))) / log(max(b, vec3(1e-30))), greaterThan(min(a, b), vec3(0.0)));
    if (op == 7) return mix(vec3(0.0), sqrt(max(a, vec3(0.0))), greaterThan(a, vec3(0.0)));
    if (op == 8) return mix(vec3(0.0), inversesqrt(max(a, vec3(1e-30))), greaterThan(a, vec3(0.0)));
    if (op == 9) return abs(a);
    if (op == 10) return exp(a);
    if (op == 11) return min(a, b);
    if (op == 12) return max(a, b);
    if (op == 13) return vec3(lessThan(a, b));
    if (op == 14) return vec3(greaterThan(a, b));
    if (op == 15) return sign(a);
    if (op == 16) return vec3(lessThanEqual(abs(a - b), max(c, vec3(1e-5))));
    if (op == 17) return smooth_min(a, b, c);
    if (op == 18) return smooth_max(a, b, c);
    if (op == 19) return floor(a + 0.5);
    if (op == 20) return floor(a);
    if (op == 21) return ceil(a);
    if (op == 22) return trunc(a);
    if (op == 23) return a - floor(a);
    if (op == 24) return mix(vec3(0.0), a - b * trunc(a / max(abs(b), vec3(1e-30)) * sign(b)), notEqual(b, vec3(0.0)));
    if (op == 25) return mix(vec3(0.0), a - floor(a / max(abs(b), vec3(1e-30)) * sign(b)) * b, notEqual(b, vec3(0.0)));
    if (op == 26) {                                                  // wrap(a, max = b, min = c)
        vec3 range = b - c;
        return mix(c, a - range * floor((a - c) / max(abs(range), vec3(1e-30)) * sign(range)), notEqual(range, vec3(0.0)));
    }
    if (op == 27) return mix(vec3(0.0), floor(a / max(abs(b), vec3(1e-30)) * sign(b)) * b, notEqual(b, vec3(0.0)));
    if (op == 28) return mix(vec3(0.0), abs(fract((a - b) / max(abs(b) * 2.0, vec3(1e-30)) * sign(b)) * b * 2.0 - b), notEqual(b, vec3(0.0)));
    if (op == 29) return sin(a);
    if (op == 30) return cos(a);
    if (op == 31) return tan(a);
    if (op == 32) return asin(clamp(a, -1.0, 1.0));
    if (op == 33) return acos(clamp(a, -1.0, 1.0));
    if (op == 34) return atan(a);
    if (op == 35) return vec3(atan(a.x, b.x), atan(a.y, b.y), atan(a.z, b.z));
    if (op == 36) return sinh(a);
    if (op == 37) return cosh(a);
    if (op == 38) return tanh(a);
    if (op == 39) return radians(a);
    return degrees(a);
}

vec4 effect(vec2 uv) {
    vec4 a = unpremultiply(src(uv)), b = unpremultiply(input_b(uv)), c = unpremultiply(input_c(uv));
    vec3 r = calc(a.rgb, b.a > 0.0 ? b.rgb : vec3(value), c.a > 0.0 ? c.rgb : vec3(value3));
    if (clamp_on) r = clamp(r, 0.0, 1.0);
    return premultiply(vec4(r, a.a));
}
