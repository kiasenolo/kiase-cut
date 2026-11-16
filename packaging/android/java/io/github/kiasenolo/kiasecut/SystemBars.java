package io.github.kiasenolo.kiasecut;

import android.app.Activity;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.View;
import android.view.WindowInsetsController;

/** Tells the Python side (kiasecut/androidbars.py reads `shown`) whether Android's system bars are on the screen.
 *
 *  With the window fullscreen a swipe from an edge brings the bars back for a moment ("transient"), and nothing the window
 *  can ask says so: the insets keep saying hidden. What does change is who may control them: the system takes the bars when
 *  they slide out and gives them back when they go, each time calling OnControllableInsetsChangedListener (with the same
 *  mask, so the calls are counted, not read). The call that comes with the registration is not a swipe. */
public final class SystemBars {
    private static final String TAG = "KiaseBars";
    private static final long LONGEST_MS = 6000;      // the bars stay about 2.5 s: a lost call cannot keep `shown` on longer than this
    public static volatile boolean shown = false;

    private static final Handler handler = new Handler(Looper.getMainLooper());
    private static final Runnable reset = new Runnable() {
        @Override public void run() {
            shown = false;
        }
    };
    private static boolean registered = false;
    private static boolean installed = false;

    private SystemBars() {}

    public static void install(final Activity activity) {
        activity.runOnUiThread(new Runnable() {
            @Override public void run() {
                if (installed) return;
                installed = true;
                try {
                    hook(activity.getWindow().getDecorView());
                } catch (Throwable t) {
                    Log.e(TAG, "hook failed", t);
                }
            }
        });
    }

    private static void hook(View decor) {
        if (Build.VERSION.SDK_INT < 30) return;
        WindowInsetsController controller = decor.getWindowInsetsController();
        if (controller == null) return;
        controller.addOnControllableInsetsChangedListener(new WindowInsetsController.OnControllableInsetsChangedListener() {
            @Override public void onControllableInsetsChanged(WindowInsetsController c, int typeMask) {
                if (!registered) {
                    registered = true;
                    return;
                }
                handler.removeCallbacks(reset);
                shown = !shown;
                if (shown) handler.postDelayed(reset, LONGEST_MS);
            }
        });
    }
}
