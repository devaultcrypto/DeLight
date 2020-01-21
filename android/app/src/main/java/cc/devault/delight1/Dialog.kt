package cc.devault.delight1

import android.app.Dialog
import android.content.DialogInterface
import android.os.Bundle
import android.view.KeyEvent
import android.view.LayoutInflater
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.widget.PopupMenu
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.fragment.app.DialogFragment
import androidx.fragment.app.viewModels
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.observe
import com.chaquo.python.PyException
import kotlinx.android.synthetic.main.password.*
import kotlin.properties.Delegates.notNull


abstract class AlertDialogFragment : DialogFragment() {
    class Model : ViewModel() {
        var started = false
    }
    private val model: Model by viewModels()

    var started = false

    override fun onCreateDialog(savedInstanceState: Bundle?): AlertDialog {
        val builder = AlertDialog.Builder(context!!)
        onBuildDialog(builder)
        return builder.create()
    }

    // Although AlertDialog creates its own view, it's helpful for that view also to be
    // returned by Fragment.getView, because:
    //   * It allows Kotlin synthetic properties to be used directly on the fragment, rather
    //     than prefixing them all with `dialog.`.
    //   * It ensures cancelPendingInputEvents is called when the fragment is stopped (see
    //     https://github.com/Electron-Cash/Electron-Cash/issues/1091#issuecomment-526951516
    //     and Fragment.initLifecycle.
    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?,
                              savedInstanceState: Bundle?): View? {
        // This isn't really consistent with the fragment lifecycle, but it's the only way to
        // make AlertDialog create its views.
        dialog.show()

        // This isn't really documented...
        val contentParent = dialog.findViewById<ViewGroup>(android.R.id.content)!!
        val content = contentParent.getChildAt(0)

        // ... so make sure we are returning the layout defined in
        // android/platform/frameworks/support/appcompat/res/layout/abc_alert_dialog_material.xml.
        val contentClassName = content.javaClass.name
        if (contentClassName != "androidx.appcompat.widget.AlertDialogLayout") {
            throw IllegalStateException("Unexpected content view $contentClassName")
        }

        // The view will be re-added in DialogFragment.onActivityCreated.
        contentParent.removeView(content)
        return content
    }

    open fun onBuildDialog(builder: AlertDialog.Builder) {}

    // We used to trigger onShowDialog from Dialog.setOnShowListener, but we had crash reports
    // indicating that the fragment context was sometimes null in that listener (#1046, #1108).
    // So use one of the fragment lifecycle methods instead.
    override fun onStart() {
        super.onStart()
        if (!started) {
            started = true
            onShowDialog()
        }
        if (!model.started) {
            model.started = true
            onFirstShowDialog()
        }
    }

    /** Can be used to do things like configure custom views, or attach listeners to buttons so
     *  they don't always close the dialog. */
    open fun onShowDialog() {}

    /** Unlike onShowDialog, this will only be called once, even if the dialog is recreated
     * after a rotation. This can be used to do things like setting the initial state of
     * editable views. */
    open fun onFirstShowDialog() {}

    override fun getDialog(): AlertDialog {
        return super.getDialog() as AlertDialog
    }
}


class MessageDialog() : AlertDialogFragment() {
    constructor(title: String, message: String) : this() {
        arguments = Bundle().apply {
            putString("title", title)
            putString("message", message)
        }
    }
    override fun onBuildDialog(builder: AlertDialog.Builder) {
        builder.setTitle(arguments!!.getString("title"))
            .setMessage(arguments!!.getString("message"))
            .setPositiveButton(android.R.string.ok, null)
    }
}


abstract class MenuDialog : AlertDialogFragment() {
    override fun onBuildDialog(builder: AlertDialog.Builder) {
        val menu = PopupMenu(app, null).menu
        onBuildDialog(builder, menu)

        val items = ArrayList<CharSequence>()
        var checkedItem: Int? = null
        for (i in 0 until menu.size()) {
            val item = menu.getItem(i)
            items.add(item.title)
            if (item.isChecked) {
                if (checkedItem != null) {
                    throw IllegalArgumentException("Menu has multiple checked items")
                }
                checkedItem = i
            }
        }

        val listener = DialogInterface.OnClickListener { _, index ->
            onMenuItemSelected(menu.getItem(index))
        }
        if (checkedItem == null) {
            builder.setItems(items.toTypedArray(), listener)
        } else {
            builder.setSingleChoiceItems(items.toTypedArray(), checkedItem, listener)
        }
    }

    abstract fun onBuildDialog(builder: AlertDialog.Builder, menu: Menu)
    abstract fun onMenuItemSelected(item: MenuItem)
}


abstract class TaskDialog<Result> : DialogFragment() {
    class Model : ViewModel() {
        var state = Thread.State.NEW
        val result = MutableLiveData<Any?>()
        val exception = MutableLiveData<ToastException>()
    }
    private val model: Model by viewModels()

    override fun onCreateDialog(savedInstanceState: Bundle?): Dialog {
        model.result.observe(this, {
            onFinished {
                @Suppress("UNCHECKED_CAST")
                onPostExecute(it as Result)
            }
        })
        model.exception.observe(this, {
            onFinished { it!!.show() }
        })

        isCancelable = false
        @Suppress("DEPRECATION")
        return android.app.ProgressDialog(this.context).apply {
            setMessage(getString(R.string.please_wait))
        }
    }

    override fun onStart() {
        super.onStart()
        if (model.state == Thread.State.NEW) {
            try {
                model.state = Thread.State.RUNNABLE
                onPreExecute()
                Thread {
                    try {
                        model.result.postValue(doInBackground())
                    } catch (e: ToastException) {
                        model.exception.postValue(e)
                    }
                }.start()
            } catch (e: ToastException) {
                model.exception.postValue(e)
            }
        }
    }

    private fun onFinished(body: () -> Unit) {
        if (model.state == Thread.State.RUNNABLE) {
            model.state = Thread.State.TERMINATED
            body()
            dismiss()
        }
    }

    /** This method is called on the UI thread. doInBackground will be called on the same
     * fragment instance after it returns. If this method throws a ToastException, it will be
     * displayed, and doInBackground will not be called. */
    open fun onPreExecute() {}

    /** This method is called on a background thread. It should not access user interface
     * objects in any way, as they may be destroyed by rotation and other events. If this
     * method throws a ToastException, it will be displayed, and onPostExecute will not be
     * called. */
    abstract fun doInBackground(): Result

    /** This method is called on the UI thread after doInBackground returns. Unlike
     * onPreExecute, it may be called on a different fragment instance. */
    open fun onPostExecute(result: Result) {}
}


abstract class TaskLauncherDialog<Result> : AlertDialogFragment() {
    override fun onShowDialog() {
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            // It's possible for multiple button clicks to be queued before the listener runs,
            // but showDialog will ensure that the progress dialog (and therefore the task) is
            // only created once.
            showDialog(activity!!, LaunchedTaskDialog<Result>().apply {
                setTargetFragment(this@TaskLauncherDialog, 0)
            })
        }
    }

    // See notes in TaskDialog.
    open fun onPreExecute() {}
    abstract fun doInBackground(): Result
    open fun onPostExecute(result: Result) {}
}


class LaunchedTaskDialog<Result> : TaskDialog<Result>() {
    @Suppress("UNCHECKED_CAST")
    val launcher by lazy { targetFragment as TaskLauncherDialog<Result> }

    override fun onPreExecute() = launcher.onPreExecute()
    override fun doInBackground() = launcher.doInBackground()

    override fun onPostExecute(result: Result) {
        launcher.onPostExecute(result)
        launcher.dismiss()
    }
}


abstract class PasswordDialog<Result> : TaskLauncherDialog<Result>() {
    var password: String by notNull()

    override fun onBuildDialog(builder: AlertDialog.Builder) {
        builder.setTitle(R.string.Enter_password)
            .setView(R.layout.password)
            .setPositiveButton(android.R.string.ok, null)
            .setNegativeButton(android.R.string.cancel, null)
    }

    override fun onCreateDialog(savedInstanceState: Bundle?): AlertDialog {
        val dialog = super.onCreateDialog(savedInstanceState)
        dialog.window!!.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE)
        return dialog
    }

    override fun onShowDialog() {
        super.onShowDialog()
        etPassword.setOnEditorActionListener { _, actionId: Int, event: KeyEvent? ->
            // See comments in ConsoleActivity.createInput.
            if (actionId == EditorInfo.IME_ACTION_DONE ||
                event?.action == KeyEvent.ACTION_UP) {
                dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick()
            }
            true
        }
    }

    override fun onPreExecute() {
        password = etPassword.text.toString()
    }

    override fun doInBackground(): Result {
        try {
            return onPassword(password)
        } catch (e: PyException) {
            throw if (e.message!!.startsWith("InvalidPassword"))
                ToastException(R.string.incorrect_password, Toast.LENGTH_SHORT) else e
        }
    }

    /** Attempt to perform the operation with the given password. If the operation fails, this
     * method should throw either a ToastException, or an InvalidPassword PyException (most
     * Python functions that take passwords will do this automatically).
     *
     * This method is called on a background thread. It should not access user interface
     * objects in any way, as they may be destroyed by rotation and other events. */
    abstract fun onPassword(password: String): Result
}
