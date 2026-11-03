// @filter 數學
// @category 節點
// @description 節點用：圖像的每個顏色通道和 B（沒接 B 就用「數值」）做運算，透明度不變
// @source 圖像
// @input b "B"
// @param op menu 相加 "相加|相減|相乘|相除|次方|最小|最大|大於|小於|絕對值|取餘數" "運算"
// @param value float 0.5 -1000 1000 "數值"
// @param clamp_on bool false "限制在 0~1"

vec3 calc(vec3 a, vec3 b) {
    if (op == 1) return a - b;
    if (op == 2) return a * b;
    if (op == 3) return mix(vec3(0.0), a / b, notEqual(b, vec3(0.0)));
    if (op == 4) return pow(max(a, vec3(0.0)), b);
    if (op == 5) return min(a, b);
    if (op == 6) return max(a, b);
    if (op == 7) return vec3(greaterThan(a, b));
    if (op == 8) return vec3(lessThan(a, b));
    if (op == 9) return abs(a);
    if (op == 10) return mix(vec3(0.0), mod(a, b), notEqual(b, vec3(0.0)));
    return a + b;
}

vec4 effect(vec2 uv) {
    vec4 a = unpremultiply(src(uv)), b = unpremultiply(input_b(uv));
    vec3 r = calc(a.rgb, b.a > 0.0 ? b.rgb : vec3(value));
    if (clamp_on) r = clamp(r, 0.0, 1.0);
    return premultiply(vec4(r, a.a));
}
