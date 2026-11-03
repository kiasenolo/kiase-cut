// @filter 分離色彩
// @category 轉換器
// @description 節點用：照 Blender 的「分離色彩」：把圖像分成四張灰階圖（RGB、HSV、HSL、YCC 或 YUV 的三個值，加上透明度），各有一個輸出
// @output c1 "紅／色相／Y"
// @output c2 "綠／飽和度／Cb／U"
// @output c3 "藍／明度／Cr／V"
// @output a "透明度"
// @param mode menu RGB "RGB|HSV|HSL|YCC|YUV" "模式"
// @param ycc_mode menu "ITU 709" "ITU 601|ITU 709|JPEG" "YCC 標準"
// @enable ycc_mode mode == YCC

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

vec3 hue_rgb(float h) { return clamp(abs(fract(h + vec3(0.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0) - 1.0, 0.0, 1.0); }
vec3 hsv_to_rgb(vec3 c) { return c.z * mix(vec3(1.0), hue_rgb(c.x), c.y); }
vec3 hsl_to_rgb(vec3 c) { return (hue_rgb(c.x) - 0.5) * (1.0 - abs(2.0 * c.z - 1.0)) * c.y + c.z; }

// YCbCr (Blender: ITU 601, ITU 709, JPEG; values 0 - 1 as Blender's, with the 16 / 128 offsets) and YUV (analog, U and V
// go below 0). Matrices by columns.
mat3 ycc_matrix() {
    if (ycc_mode == 0) return transpose(mat3(0.257, 0.504, 0.098, -0.148, -0.291, 0.439, 0.439, -0.368, -0.071));
    if (ycc_mode == 1) return transpose(mat3(0.183, 0.614, 0.062, -0.101, -0.339, 0.439, 0.439, -0.399, -0.040));
    return transpose(mat3(0.299, 0.587, 0.114, -0.16874, -0.33126, 0.5, 0.5, -0.41869, -0.08131));
}
vec3 ycc_offset() { return vec3(ycc_mode == 2 ? 0.0 : 16.0 / 255.0, 128.0 / 255.0, 128.0 / 255.0); }
mat3 yuv_matrix() { return transpose(mat3(0.299, 0.587, 0.114, -0.147, -0.289, 0.436, 0.615, -0.515, -0.100)); }
vec3 rgb_to_ycc(vec3 c) { return ycc_matrix() * c + ycc_offset(); }
vec3 ycc_to_rgb(vec3 c) { return inverse(ycc_matrix()) * (c - ycc_offset()); }
vec3 rgb_to_yuv(vec3 c) { return yuv_matrix() * c; }
vec3 yuv_to_rgb(vec3 c) { return inverse(yuv_matrix()) * c; }

vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    vec3 v = mode == 1 ? rgb_to_hsv(c.rgb) : mode == 2 ? rgb_to_hsl(c.rgb) : mode == 3 ? rgb_to_ycc(c.rgb)
           : mode == 4 ? rgb_to_yuv(c.rgb) : c.rgb;
    float x = output_index == 0 ? v.x : output_index == 1 ? v.y : output_index == 2 ? v.z : c.a;
    return vec4(vec3(x), 1.0);
}
