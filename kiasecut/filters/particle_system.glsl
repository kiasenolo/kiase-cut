// @filter 粒子系統
// @category 粒子
// @description 通用的粒子系統：發射器（點、線、圓、矩形、圖片）、重力／風／阻力／亂流／地面反彈、隨生命變化的大小和顏色、各種粒子形狀、拖尾；火花、雪、煙火、光點都能用它做。套在透明的片段上就是一個粒子物件，套在有圖片的片段上可以從圖片噴出粒子
// @particles 200000 count*(trail+1)
// @param count int 400 1 20000 "粒子數"
// @param mode menu 持續 "持續|爆發" "發射方式"
// @param life float 2 0.1 30 "壽命（秒）"
// @param life_var float 0.3 0 1 "壽命差異"
// @param period float 4 0.2 60 "爆發間隔（秒）"
// @enable period mode == 爆發
// @param time_offset float 0 0 120 "時間偏移（秒）"
// @panel 發射器
// @param emitter menu 點 "點|線|圓形|矩形|圖片" "形狀"
// @param origin vec2 0.5,0.5 -1 2 "位置"
// @param ewidth float 400 0 4000 "寬（像素）"
// @param eheight float 300 0 4000 "高（像素）"
// @param erot float 0 -360 360 "旋轉（度）"
// @param threshold float 0.1 0 1 "透明度門檻"
// @param tint bool true "顏色取自圖片"
// @param hide_src bool false "隱藏原畫面"
// @enable ewidth emitter != 點|圖片
// @enable eheight emitter == 矩形
// @enable erot emitter != 點|圖片
// @enable threshold emitter == 圖片
// @enable tint emitter == 圖片
// @enable hide_src emitter == 圖片
// @panel 運動
// @param outward bool false "從發射位置向外"
// @param angle float 0 -360 360 "方向（度，0 向上）"
// @param spread float 360 0 360 "散開角度"
// @param speed float 250 0 4000 "初速（像素／秒）"
// @param speed_var float 0.5 0 1 "初速差異"
// @enable angle !outward
// @enable spread !outward
// @panel 力
// @param gravity float 300 -3000 3000 "重力（像素／秒²）"
// @param wind float 0 -2000 2000 "風（像素／秒²）"
// @param drag float 0.3 0 10 "空氣阻力"
// @param turb float 0 0 500 "亂流（像素）"
// @param turb_scale float 200 10 2000 "亂流大小（像素）"
// @param turb_speed float 0.5 0 5 "亂流速度"
// @param floor_on bool false "地面（反彈）"
// @param floor_y float 0.9 0 1 "地面高度（0 上、1 下）"
// @param bounce float 0.5 0 1 "彈性"
// @enable floor_y floor_on
// @enable bounce floor_on
// @enable turb_scale turb
// @enable turb_speed turb
// @panel 外觀
// @param look menu 柔邊圓 "柔邊圓|實心圓|方塊|多邊形|星芒|線條" "形狀"
// @param sides int 5 3 12 "邊數"
// @param softness float 0.6 0 1 "柔邊"
// @param size float 12 0.5 300 "大小（像素）"
// @param size_var float 0.4 0 1 "大小差異"
// @param size_end float 0.3 0 4 "結束時大小（倍）"
// @param size_curve curve 0,0,1,1 "大小變化曲線"
// @param stretch float 0 0 0.5 "依速度拉長（秒）"
// @param rotmode menu 固定 "固定|隨機|旋轉|順著運動" "朝向"
// @param spin float 2 -30 30 "旋轉速度"
// @param colors gradient 0:#fff3c4,0.5:#ffa43a,1:#ff3b1a "顏色（隨生命）"
// @param alpha float 1 0 1 "不透明度"
// @param fade_in float 0.05 0 1 "淡入（占壽命）"
// @param fade_out float 0.4 0 1 "淡出（占壽命）"
// @param brightness float 1 0 8 "亮度"
// @param glow float 1 0 1 "發光（疊加）"
// @param twinkle float 0 0 1 "閃爍"
// @enable sides look == 多邊形
// @enable softness look == 柔邊圓
// @enable spin rotmode == 旋轉
// @panel 拖尾
// @param trail int 0 0 16 "拖尾段數"
// @param trail_step float 0.03 0.005 0.3 "段與段的間隔（秒）"
// @param trail_fade float 0.8 0 1 "尾巴變淡"
// @enable trail_step trail
// @enable trail_fade trail
// @param seed float 0 0 100 "種子"
// @step 10 ewidth eheight speed gravity wind turb turb_scale

// A general particle system, stateless like sparks.glsl: where particle i is follows from its number, the time and the settings,
// so any frame is drawn on its own. Slot i is born again every `life` seconds (staggered by i / count) or, as a burst, all of
// them every `period` seconds; `k` (which birth it is) is part of every random number, so each birth is different.
// Motion is closed form: v' = acceleration - drag v; with 地面 the vertical motion bounces off the floor (without drag) and
// 亂流 adds a smooth displacement. A trail is the same particle drawn at `trail` earlier moments: instance = particle * (trail + 1) + copy.
// Not here, because they need what other particles or the picture did: collisions between particles, pushing by the picture.

float R(int i, float k, float salt) {
    return rand(vec2(float(i) * 0.6180339 + seed * 3.7 + salt * 11.3, k * 1.7321 + salt * 5.11 + 0.5));
}

float vnoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(rand(i), rand(i + vec2(1.0, 0.0)), f.x), mix(rand(i + vec2(0.0, 1.0)), rand(i + vec2(1.0, 1.0)), f.x), f.y);
}

vec2 turn(vec2 v, float a) { float c = cos(a), s = sin(a); return vec2(c * v.x - s * v.y, s * v.x + c * v.y); }

vec4 effect(vec2 uv) {
    return (hide_src && emitter == 4) ? vec4(0.0) : src(uv);
}

bool particle(int id, out Particle p) {
    int copies = trail + 1;
    int i = id / copies;
    int copy = id - i * copies;
    float s, k;
    float tt = time + time_offset;
    if (mode == 0) {
        s = tt - float(i) * life / float(count);
        if (s < 0.0) return false;
        k = floor(s / life);
        s -= k * life;
    } else {
        k = floor(tt / period);
        s = tt - k * period;
    }
    float lf = life * (1.0 - life_var * R(i, k, 1.0));
    s -= float(copy) * trail_step;                                 // a trail copy: the same particle, a little earlier
    if (s < 0.0 || s >= lf) return false;
    float u = s / lf;

    // where it starts
    vec2 centre = origin * resolution;
    vec2 base = centre;
    vec4 pic = vec4(1.0);
    float ra = R(i, k, 2.0), rb = R(i, k, 3.0);
    if (emitter == 1) {
        base += turn(vec2((ra - 0.5) * ewidth, 0.0), radians(erot));
    } else if (emitter == 2) {
        float rr = 0.5 * ewidth * sqrt(ra), ang = rb * 6.2831853;
        base += turn(vec2(cos(ang), sin(ang)) * rr, radians(erot));
    } else if (emitter == 3) {
        base += turn(vec2((ra - 0.5) * ewidth, (rb - 0.5) * eheight), radians(erot));
    } else if (emitter == 4) {                                     // anywhere the picture is there: a few tries
        bool found = false;
        for (int t = 0; t < 12; t++) {
            vec2 q = vec2(R(i, k, 20.0 + float(t)), R(i, k, 40.0 + float(t)));
            vec4 c = src(q);
            if (c.a > threshold) {
                base = q * resolution;
                pic = c.a > 0.0 ? vec4(c.rgb / c.a, c.a) : vec4(1.0);
                found = true;
                break;
            }
        }
        if (!found) return false;
        centre = 0.5 * resolution;
    }

    // where it is, s seconds on
    vec2 dir;
    vec2 away = base - centre;
    if (outward && length(away) > 0.5) {
        dir = normalize(away);
    } else {
        float a = radians(angle + (R(i, k, 4.0) - 0.5) * spread);
        dir = vec2(sin(a), -cos(a));
    }
    vec2 v0 = dir * speed * (1.0 - speed_var * R(i, k, 5.0));
    vec2 acc = vec2(wind, gravity);
    vec2 pos = base, vel;
    if (drag > 0.001) {
        vec2 vt = acc / drag;
        float e = exp(-drag * s);
        vel = vt + (v0 - vt) * e;
        pos += vt * s + (v0 - vt) * (1.0 - e) / drag;
    } else {
        vel = v0 + acc * s;
        pos += v0 * s + 0.5 * acc * s * s;
    }
    if (floor_on && gravity > 0.0) {                               // the vertical motion again, bouncing (no drag)
        float fy = floor_y * resolution.y;
        float y = base.y, vy = v0.y, left = s;
        for (int b = 0; b < 8; b++) {
            float c = y - fy;                                      // (above the floor: negative)
            float disc = vy * vy - 2.0 * gravity * c;
            float th = c >= 0.0 ? 0.0 : (-vy + sqrt(max(disc, 0.0))) / gravity;
            if (th > left || (c >= 0.0 && abs(vy) < 1.0)) break;
            left -= th;
            vy = -(vy + gravity * th) * bounce;
            y = fy;
            if (abs(vy) < 4.0) { vy = 0.0; break; }
        }
        float below = y - fy;
        pos.y = below >= 0.0 && vy == 0.0 ? fy : y + vy * left + 0.5 * gravity * left * left;
        pos.y = min(pos.y, fy);
        vel.y = vy + gravity * left;
    }
    if (turb > 0.0) {
        vec2 q = pos / turb_scale;
        float tz = tt * turb_speed;
        pos += turb * (1.0 - exp(-3.0 * s)) * (vec2(vnoise(q + vec2(tz, 0.0)), vnoise(q + vec2(17.3, tz))) - 0.5) * 2.0;
    }

    // how it looks
    float sz = size * (1.0 - size_var * R(i, k, 6.0)) * mix(1.0, size_end, curve_ease(size_curve, u));
    float spd = length(vel);
    vec2 heading = spd > 0.001 ? vel / spd : vec2(1.0, 0.0);
    p.rot = rotmode == 1 ? R(i, k, 7.0) * 6.2831853 : rotmode == 2 ? R(i, k, 7.0) * 6.2831853 + spin * s : atan(heading.y, heading.x);
    p.size = vec2(sz);
    p.pos = pos;
    if (look == 5 || stretch > 0.0) {                              // a streak: along the motion, the head where the particle is
        float half_len = sz + 0.5 * spd * (look == 5 ? max(stretch, 0.04) : stretch);
        p.rot = atan(heading.y, heading.x);
        p.size = vec2(half_len, look == 5 ? sz * 0.5 : sz);
        p.pos = pos - heading * (half_len - sz);
    } else if (rotmode == 0) {
        p.rot = 0.0;
    }

    vec4 c = gradient_eval(colors_p, colors_c, colors_n, u, 2, 0, 0);
    if (emitter == 4 && tint) c.rgb *= pic.rgb;
    float fin = fade_in > 0.0 ? smoothstep(0.0, fade_in, u) : 1.0;
    float fout = fade_out > 0.0 ? 1.0 - smoothstep(1.0 - fade_out, 1.0, u) : 1.0;
    float tw = 1.0 - twinkle * (0.5 + 0.5 * sin(tt * (8.0 + 10.0 * R(i, k, 8.0)) + 60.0 * R(i, k, 9.0)));
    c.rgb *= brightness * tw;
    c.a *= alpha * fin * fout * (1.0 - trail_fade * float(copy) / float(copies));
    p.color = c;
    p.data = vec4(u, R(i, k, 10.0), 1.5 / max(min(p.size.x, p.size.y), 1.0), 0.0);
    return true;
}

vec4 sprite(vec2 q, vec4 color, vec4 data) {
    float a;
    float soft = data.z;
    if (look == 0) {                                               // a soft glow
        float d = length(q);
        a = exp(-d * d * (1.0 + (1.0 - softness) * 7.0)) * (1.0 - smoothstep(0.85, 1.0, d));
    } else if (look == 1) {
        a = 1.0 - smoothstep(1.0 - soft, 1.0, length(q));
    } else if (look == 2) {
        vec2 e = (1.0 - abs(q)) / soft;
        a = clamp(min(e.x, e.y), 0.0, 1.0);
    } else if (look == 3) {
        float seg = 6.2831853 / float(sides);
        float t = mod(atan(q.y, q.x) + 6.2831853, seg) - 0.5 * seg;
        a = 1.0 - smoothstep(1.0 - soft, 1.0, length(q) / (cos(0.5 * seg) / cos(t)));
    } else if (look == 4) {                                        // a four-pointed sparkle
        vec2 w = abs(q);
        float cross_ = max((1.0 - w.x) * exp(-w.y * 14.0), (1.0 - w.y) * exp(-w.x * 14.0));
        a = clamp(cross_ + exp(-dot(q, q) * 10.0) * 0.8, 0.0, 1.0) * (1.0 - smoothstep(0.9, 1.0, max(w.x, w.y)));
    } else {                                                       // a streak: dim tail, bright head
        float across = 1.0 - smoothstep(0.0, 1.0, abs(q.y));
        across *= across;
        float along = mix(0.2, 1.0, smoothstep(-1.0, 1.0, q.x) * smoothstep(-1.0, 1.0, q.x));
        a = across * along * smoothstep(-1.0, -0.6, q.x) * (1.0 - smoothstep(0.75, 1.0, q.x));
    }
    return vec4(color.rgb * color.a * a, color.a * a * (1.0 - glow));
}
