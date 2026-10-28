// @filter 下雨
// @category 天氣
// @description 雨絲從上面落下，遠近三層，可以斜著下
// @param amount float 0.5 0 1 "雨量"
// @param speed float 1 0 4 "速度"
// @param angle float 10 -60 60 "傾斜"
// @param streak float 0.08 0.01 0.4 "雨絲長度"
// @param opacity float 0.5 0 1 "亮度"
// @param color color #c8d8ff "顏色"
// @param darken float 0.15 0 1 "畫面變暗"

// one layer of streaks: columns of `cols` per picture height, each with drops falling at its
// own offset; returns how much streak covers p (height units)
float layer(vec2 p, float cols, float fall, float len, float width, float seed) {
    float col = floor(p.x * cols);
    float x = fract(p.x * cols);
    float rows = 1.0 / (len * 2.5);                       // room for one streak and a gap per cell
    float y = p.y * rows - fall * rows + rand(vec2(col, seed)) * 10.0;
    float cell = floor(y);
    float inside = fract(y);
    if (rand(vec2(col, cell + seed)) > amount) return 0.0;
    float cx = 0.2 + 0.6 * rand(vec2(cell, col + seed));
    float w = width * cols;                               // the width in this cell's x units
    float across = 1.0 - smoothstep(w * 0.3, w, abs(x - cx));
    float along = smoothstep(0.0, 0.4, inside) * step(inside, 0.4) / 0.4 * inside;   // bright head below
    return across * along;
}

vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    float a = radians(angle);
    vec2 p = vec2(uv.x * resolution.x / resolution.y, uv.y);
    p = vec2(cos(a) * p.x + sin(a) * p.y, -sin(a) * p.x + cos(a) * p.y);
    float px = 1.0 / resolution.y;
    float r = layer(p, 60.0, time * speed * 2.2, streak, 1.6 * px, 1.0) * 0.6
            + layer(p + 0.37, 35.0, time * speed * 3.0, streak * 1.4, 2.4 * px, 2.0) * 0.8
            + layer(p + 0.71, 18.0, time * speed * 4.2, streak * 2.0, 3.5 * px, 3.0);
    float k = clamp(r, 0.0, 1.0) * opacity * color.a;
    vec3 rgb = c.rgb * (1.0 - darken * 0.5);
    rgb = mix(rgb, color.rgb * c.a, k);
    return vec4(rgb, c.a);
}
