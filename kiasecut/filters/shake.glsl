// @filter 晃動
// @category 動態
// @description 手持鏡頭般的隨機晃動（稍微放大，邊緣才不會露出來）
// @param amount float 20 0 300 "幅度"
// @param rotation float 1.5 0 45 "旋轉幅度"
// @param speed float 8 0 60 "速度"
// @param zoom float 1.05 1 2 "放大"
float wobble(float x, float seed) {
    float i = floor(x), f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(rand(vec2(i, seed)), rand(vec2(i + 1.0, seed)), f) * 2.0 - 1.0;
}
vec4 effect(vec2 uv) {
    float t = time * speed;
    vec2 asp = vec2(resolution.x / resolution.y, 1.0);
    vec2 off = vec2(wobble(t, 1.0), wobble(t, 2.0)) * amount * scale / resolution;
    float a = wobble(t, 3.0) * radians(rotation);
    vec2 d = mat2(cos(a), sin(a), -sin(a), cos(a)) * ((uv - 0.5) * asp) / max(zoom, 0.01);
    return src(0.5 + d / asp + off);
}
