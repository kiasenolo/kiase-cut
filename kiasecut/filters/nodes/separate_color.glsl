// @filter 分離色彩
// @category 節點
// @description 節點用：把圖像分成四張灰階圖（紅綠藍或色相／飽和度／明度，加上透明度），各有一個輸出
// @output c1 "紅／色相"
// @output c2 "綠／飽和度"
// @output c3 "藍／明度"
// @output a "透明度"
// @param mode menu RGB "RGB|HSV|HSL" "模式"

vec3 rgb_to_hsv(vec3 c) {
    float mx = max(c.r, max(c.g, c.b));
    float mn = min(c.r, min(c.g, c.b));
    float d = mx - mn;
    float h = 0.0;
    if (d > 1e-6) {
        if (mx == c.r) h = mod((c.g - c.b) / d, 6.0);
        else if (mx == c.g) h = (c.b - c.r) / d + 2.0;
        else h = (c.r - c.g) / d + 4.0;
        h /= 6.0;
    }
    return vec3(h, mx > 1e-6 ? d / mx : 0.0, mx);
}

vec3 rgb_to_hsl(vec3 c) {
    float mx = max(c.r, max(c.g, c.b));
    float mn = min(c.r, min(c.g, c.b));
    float l = (mx + mn) * 0.5;
    float d = mx - mn;
    float s = d < 1e-6 ? 0.0 : d / (1.0 - abs(2.0 * l - 1.0));
    return vec3(rgb_to_hsv(c).x, s, l);
}

vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    vec3 v = mode == 1 ? rgb_to_hsv(c.rgb) : mode == 2 ? rgb_to_hsl(c.rgb) : c.rgb;
    float x = output_index == 0 ? v.x : output_index == 1 ? v.y : output_index == 2 ? v.z : c.a;
    return vec4(vec3(x), 1.0);
}
