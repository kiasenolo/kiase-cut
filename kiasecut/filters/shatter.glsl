// @filter 圖片碎裂
// @category 粒子
// @description 畫面切成一格一格的碎片，從一點往外、一個方向掃過，或隨機地炸開飛走，帶重力、翻轉、縮小和淡出；也可以倒著播，碎片飛回來拼成畫面
// @particles 60000
// @param cols int 100 8 200 "每列碎片數"
// @param mode menu 從點擴散 "從點擴散|掃過|隨機" "觸發方式"
// @param reverse bool false "倒著播（拼回來）"
// @param start float 0.5 0 30 "開始（秒）"
// @param spread float 1 0 30 "擴散時間（秒）"
// @param jitter float 0.3 0 1 "隨機程度"
// @param life float 2 0.2 20 "碎片壽命（秒）"
// @panel 觸發位置
// @param origin vec2 0.5,0.5 -1 2 "擴散中心"
// @param angle float 0 -360 360 "掃過方向（度，0 往右）"
// @enable origin mode != 掃過
// @enable angle mode == 掃過
// @panel 運動
// @param blast float 300 0 3000 "爆開速度（像素／秒）"
// @param scatter float 0.4 0 1 "散亂"
// @param gravity float 500 -3000 3000 "重力（像素／秒²）"
// @param drag float 0.6 0 10 "空氣阻力"
// @param wind float 0 -2000 2000 "風（像素／秒²）"
// @param turbulence float 30 0 300 "飄動（像素）"
// @param spin float 3 0 30 "旋轉速度"
// @param shrink float 0.4 0 1 "縮小"
// @param seed float 0 0 100 "種子"
// @step 10 blast gravity wind turbulence

// The picture is a grid of cols x rows pieces; piece i leaves at its trigger time (the distance from a point, along a
// direction, or at random, spread over `spread` seconds) and flies for `life` seconds. Where a piece has left the picture is
// transparent (effect()), and the piece itself - a quad that reads its own cell of the picture, sprite() - moves on from there.
// Nothing is kept from one frame to the next, so any frame is drawn on its own (see sparks.glsl); played backwards the
// pieces fly back and join up at the end.

float R(int i, float salt) {
    return rand(vec2(float(i) * 0.6180339 + seed * 3.7 + salt * 11.3, salt * 5.11 + 0.5));
}

int rows_n() {                                                  // about square pieces, and never more than the particles there are
    return max(1, min(int(floor(float(cols) * resolution.y / resolution.x + 0.5)), 60000 / cols));
}

float now() { return reverse ? start + spread + life - time : time; }

// when piece i leaves
float trig(int i) {
    int rn = rows_n();
    vec2 c = (vec2(float(i % cols), float(i / cols)) + 0.5) / vec2(float(cols), float(rn));
    float asp = resolution.x / resolution.y;
    vec2 d = (c - 0.5) * vec2(asp, 1.0);
    float f;
    if (mode == 0) {
        vec2 o = (origin - 0.5) * vec2(asp, 1.0);
        float farthest = max(max(length(vec2(-0.5 * asp, -0.5) - o), length(vec2(0.5 * asp, -0.5) - o)),
                        max(length(vec2(-0.5 * asp, 0.5) - o), length(vec2(0.5 * asp, 0.5) - o)));
        f = length(d - o) / max(farthest, 1e-4);
    } else if (mode == 1) {
        float a = radians(angle);
        vec2 dir = vec2(cos(a), sin(a));
        float reach = 0.5 * (abs(dir.x) * asp + abs(dir.y));
        f = 0.5 + dot(d, dir) / (2.0 * max(reach, 1e-4));
    } else {
        f = R(i, 1.0);
    }
    return start + spread * mix(f, R(i, 1.0), jitter);
}

vec4 effect(vec2 uv) {
    int rn = rows_n();
    int cx = clamp(int(floor(uv.x * float(cols))), 0, cols - 1);
    int cy = clamp(int(floor(uv.y * float(rn))), 0, rn - 1);
    return now() >= trig(cy * cols + cx) ? vec4(0.0) : src(uv);
}

bool particle(int i, out Particle p) {
    int rn = rows_n();
    if (i >= cols * rn) return false;
    float s = now() - trig(i);
    if (s < 0.0 || s >= life) return false;
    float u = s / life;

    vec2 cell = resolution / vec2(float(cols), float(rn));
    vec2 home = (vec2(float(i % cols), float(i / cols)) + 0.5) * cell;
    vec2 away;
    if (mode == 1) {
        away = vec2(cos(radians(angle)), sin(radians(angle)));
    } else {
        vec2 d = home - origin * resolution;
        away = length(d) > 0.5 ? normalize(d) : vec2(0.0, -1.0);
    }
    vec2 rnd = vec2(R(i, 2.0) * 2.0 - 1.0, R(i, 3.0) * 2.0 - 1.0);
    vec2 v0 = normalize(mix(away, rnd / max(length(rnd), 1e-4), scatter) + vec2(1e-4)) * blast * (0.5 + R(i, 4.0));
    vec2 acc = vec2(wind, gravity);
    vec2 pos;
    if (drag > 0.001) {
        vec2 vt = acc / drag;
        pos = vt * s + (v0 - vt) * (1.0 - exp(-drag * s)) / drag;
    } else {
        pos = v0 * s + 0.5 * acc * s * s;
    }
    pos += turbulence * (1.0 - exp(-3.0 * s)) * vec2(sin(s * (2.0 + 3.0 * R(i, 5.0)) + 6.2831853 * R(i, 6.0)),
                                                       cos(s * (2.0 + 3.0 * R(i, 7.0)) + 6.2831853 * R(i, 8.0)));
    p.pos = home + pos;
    p.size = cell * 0.5 * 1.02 * (1.0 - shrink * u);                     // (a little over: no gaps between pieces that have not moved yet)
    p.rot = spin * s * (R(i, 9.0) * 2.0 - 1.0);
    p.color = vec4(1.0, 1.0, 1.0, 1.0 - smoothstep(0.6, 1.0, u));
    p.data = vec4(home / resolution, 0.5 * cell / resolution);
    return true;
}

// the piece's own part of the picture
vec4 sprite(vec2 q, vec4 color, vec4 data) {
    return src(data.xy + clamp(q, -1.0, 1.0) * data.zw) * color.a;
}
