// @filter 時間
// @category 輸入
// @description 節點用：輸出隨時間變化的灰階圖（整張同一個值），接到別的節點的數字參數就會隨時間變：片段進度 0→1、每隔一段時間從頭循環、來回、正弦波，或隨影格
// @param mode menu 片段進度 "片段進度|循環|來回|正弦波|影格循環" "模式"
// @param period float 1 0.01 600 "週期（秒；影格循環是影格數）"

vec4 effect(vec2 uv) {
    float v;
    if (mode == 0) v = progress;
    else if (mode == 1) v = fract(time / period);
    else if (mode == 2) v = 1.0 - abs(fract(time / period) * 2.0 - 1.0);
    else if (mode == 3) v = 0.5 - 0.5 * cos(6.2831853 * time / period);
    else v = fract(float(frame) / period);
    return vec4(vec3(clamp(v, 0.0, 1.0)), 1.0);
}
