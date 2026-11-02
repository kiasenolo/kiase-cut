// @filter 下雨
// @category 天氣
// @description 雨絲從上面落下，遠近三層，可以斜著下；從沒有雨開始下（時間偏移：開始時已經下了幾秒）
// @param amount float 0.5 0 4 "雨量"
// @param speed float 1 0 4 "速度"
// @param angle float 10 -60 60 "傾斜"
// @param streak float 0.08 0.01 0.4 "雨絲長度"
// @param opacity float 0.5 0 1 "亮度"
// @param color color #c8d8ff "顏色"
// @param darken float 0.15 0 1 "畫面變暗"
// @param time_offset float 0 0 120 "時間偏移（秒）"
// @param seed float 0 0 100 "種子"

float SA, CA;                                             // the slant (sin, cos), set by effect()

// one layer of streaks: columns of `cols` per picture height, each with drops falling at its
// own offset (雨量 above 1: up to four sets of columns, a fraction of a column apart); returns
// how much streak covers p (height units, slanted; off: the layer's shift). Only drops that were
// above the picture when the rain began are drawn, so it starts dry and fills as they fall in.
float layer(vec2 p, vec2 off, float cols, float fall, float len, float width, float salt) {
    float rows = 1.0 / (len * 2.5);                       // room for one streak and a gap per cell
    float w = width * cols;                               // the width in a cell's x units
    float sum = 0.0;
    for (int k = 0; k < 4; k++) {
        float have = amount - float(k);
        if (have <= 0.0) break;
        float sk = salt + seed * 3.91 + float(k) * 13.7;
        float px = p.x + off.x + float(k) * 0.37 / cols;
        float col = floor(px * cols);
        float x = fract(px * cols);
        float lift = rand(vec2(col, sk)) * 10.0;
        float y = (p.y + off.y) * rows - fall * rows + lift;
        float cell = floor(y);
        float inside = fract(y);
        if (rand(vec2(col, cell + sk)) > have) continue;
        float cx = 0.2 + 0.6 * rand(vec2(cell, col + sk));
        // where its head was when the rain began, back on the picture: it must have been above it
        vec2 at0 = vec2((col + cx) / cols - float(k) * 0.37 / cols, (cell + 0.4 - lift) / rows) - off;
        if (SA * at0.x + CA * at0.y > 0.0) continue;
        float across = 1.0 - smoothstep(w * 0.3, w, abs(x - cx));
        float along = smoothstep(0.0, 0.4, inside) * step(inside, 0.4) / 0.4 * inside;   // bright head below
        sum += across * along;
    }
    return sum;
}

vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    float a = radians(angle);
    SA = sin(a);
    CA = cos(a);
    vec2 p = vec2(uv.x * resolution.x / resolution.y, uv.y);
    p = vec2(CA * p.x + SA * p.y, -SA * p.x + CA * p.y);
    float px = 1.0 / resolution.y;
    float t = (time + time_offset) * speed;
    float r = layer(p, vec2(0.0), 60.0, t * 2.2, streak, 1.6 * px, 1.0) * 0.6
            + layer(p, vec2(0.37), 35.0, t * 3.0, streak * 1.4, 2.4 * px, 2.0) * 0.8
            + layer(p, vec2(0.71), 18.0, t * 4.2, streak * 2.0, 3.5 * px, 3.0);
    float k = clamp(r, 0.0, 1.0) * opacity * color.a;
    vec3 rgb = c.rgb * (1.0 - darken * 0.5);
    rgb = mix(rgb, color.rgb * c.a, k);
    return vec4(rgb, c.a);
}
