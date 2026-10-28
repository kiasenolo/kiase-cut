// @filter 緩慢推近
// @category 動態
// @description 整段時間從一個大小慢慢縮放、平移到另一個（Ken Burns 效果）；起始比結束大就是拉遠
// @param zoom_from float 1 1 4 "起始放大"
// @param zoom_to float 1.2 1 4 "結束放大"
// @param from vec2 0.5,0.5 0 1 "起始中心"
// @param to vec2 0.5,0.5 0 1 "結束中心"
// @param easing menu 平滑 "線性|平滑|漸快|漸慢" "速度變化"
vec4 effect(vec2 uv) {
    float t = clamp(progress, 0.0, 1.0);
    if (easing == 1) t = t * t * (3.0 - 2.0 * t);
    else if (easing == 2) t = t * t;
    else if (easing == 3) t = 1.0 - (1.0 - t) * (1.0 - t);
    float z = max(mix(zoom_from, zoom_to, t), 0.01);
    // the centre may only go as far as the zoomed picture still covers the frame
    vec2 c = clamp(mix(from, to, t), vec2(0.5 / z), vec2(1.0 - 0.5 / z));
    return src(c + (uv - 0.5) / z);
}
