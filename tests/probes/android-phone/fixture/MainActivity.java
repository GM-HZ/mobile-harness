package org.mobileharness.phonefixture;

import android.app.Activity;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.SystemClock;
import android.text.InputType;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private EditText note;
    private float swipeStartX;
    private float swipeStartY;
    private int swipeMoves;

    @Override
    protected void onCreate(Bundle savedState) {
        super.onCreate(savedState);
        SharedPreferences config = getSharedPreferences("fixture_config", MODE_PRIVATE);
        int launchDelay = config.getInt("launch_delay_ms", 0);
        SystemClock.sleep(Math.max(0, Math.min(launchDelay, 4000)));
        SharedPreferences gestures = getSharedPreferences("gestures", MODE_PRIVATE);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_HIDDEN);
        ScrollView scroll = new ScrollView(this);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(48, 96, 48, 48);
        layout.setFocusableInTouchMode(true);

        TextView state = new TextView(this);
        state.setTextSize(26);
        state.setText(gestures.getBoolean("sample_on", false) ? "SAMPLE_ON" : "SAMPLE_OFF");
        layout.addView(state);

        Button toggle = new Button(this);
        toggle.setText("Toggle sample");
        toggle.setOnClickListener(view -> {
            boolean sampleOn = !gestures.getBoolean("sample_on", false);
            boolean saved = gestures.edit().putBoolean("sample_on", sampleOn).commit();
            state.setText(!saved ? "SAMPLE_SAVE_FAILED" : sampleOn ? "SAMPLE_ON" : "SAMPLE_OFF");
        });
        layout.addView(toggle);

        note = new EditText(this);
        note.setHint("Fixture note");
        note.setInputType(InputType.TYPE_CLASS_TEXT);
        note.setSingleLine(true);
        if (savedState != null) note.setText(savedState.getString("note", ""));
        layout.addView(note);

        TextView hitCount = new TextView(this);
        hitCount.setText("COORD_HITS_" + gestures.getInt("hits", 0));
        layout.addView(hitCount);
        View target = new View(this);
        target.setBackgroundColor(0xffff00ff);
        target.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        target.setOnTouchListener((view, event) -> {
            if (event.getActionMasked() == MotionEvent.ACTION_UP) {
                int hits = gestures.getInt("hits", 0) + 1;
                boolean saved = gestures.edit().putInt("hits", hits).commit();
                hitCount.setText(saved ? "COORD_HITS_" + hits : "COORD_SAVE_FAILED");
            }
            return true;
        });
        float density = getResources().getDisplayMetrics().density;
        layout.addView(target, Math.round(128 * density), Math.round(56 * density));

        TextView swipeCount = new TextView(this);
        swipeCount.setText("SWIPE_HITS_" + gestures.getInt("swipe_hits", 0));
        layout.addView(swipeCount);
        View swipeTarget = new View(this);
        swipeTarget.setBackgroundColor(0xff00e8ff);
        swipeTarget.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        swipeTarget.setOnTouchListener((view, event) -> {
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    swipeStartX = event.getX();
                    swipeStartY = event.getY();
                    swipeMoves = 0;
                    break;
                case MotionEvent.ACTION_MOVE:
                    swipeMoves++;
                    break;
                case MotionEvent.ACTION_UP:
                    float dx = event.getX() - swipeStartX;
                    float dy = event.getY() - swipeStartY;
                    if (swipeMoves > 0 && dx > 80 * density && Math.abs(dy) < 16 * density) {
                        int hits = gestures.getInt("swipe_hits", 0) + 1;
                        boolean saved = gestures.edit().putInt("swipe_hits", hits)
                                .putInt("swipe_dx", Math.round(dx)).commit();
                        swipeCount.setText(saved ? "SWIPE_HITS_" + hits : "SWIPE_SAVE_FAILED");
                    }
                    break;
            }
            return true;
        });
        layout.addView(swipeTarget, Math.round(250 * density), Math.round(52 * density));

        Button secure = new Button(this);
        secure.setText("Protect fixture window");
        secure.setOnClickListener(view -> {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
            secure.setText("Fixture window protected");
        });
        layout.addView(secure);

        // Keep the result outside the initial viewport on phones and tablets.
        TextView rows = new TextView(this);
        String imageTag = config.getString("image_tag", "");
        rows.setText(imageTag.isEmpty() ? "Scroll to the fixture result" : "Fixture image " + imageTag);
        rows.setMinHeight(getResources().getDisplayMetrics().heightPixels);
        layout.addView(rows);

        SharedPreferences form = getSharedPreferences("form", MODE_PRIVATE);
        String savedNote = form.getString("saved_note", null);
        TextView result = new TextView(this);
        result.setText(savedNote == null ? "FORM_NOT_SAVED" : "FORM_SAVED " + savedNote);
        Button save = new Button(this);
        save.setText("Save fixture note");
        save.setOnClickListener(view -> {
            String value = note.getText().toString();
            boolean saved = form.edit().putString("saved_note", value).commit();
            result.setText(saved ? "FORM_SAVED " + value : "FORM_SAVE_FAILED");
        });
        layout.addView(save);
        layout.addView(result);
        scroll.addView(layout);
        setContentView(scroll);
        layout.requestFocus();
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        outState.putString("note", note.getText().toString());
        super.onSaveInstanceState(outState);
    }
}
