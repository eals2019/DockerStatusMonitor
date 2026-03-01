#!/usr/bin/env python3
"""
Docker Status Monitor with Notification System - TEST VERSION
Features:
- Bell icon with notification count badge
- Collapsible notification sidebar
- Consolidated "Container Updates Available" notification
- Version comparison when expanded
- General notification framework for future use
"""

import subprocess
import tkinter as tk
from tkinter import ttk
import threading
import time
import re
import os
import sys
import signal
from datetime import datetime
from pathlib import Path

# Import the version checker
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

try:
    from version_checker import (
        check_all_updates, 
        get_updates_with_notifications,
        get_last_check_time,
        get_cached_results
    )
    VERSION_CHECKER_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Version checker not available: {e}")
    VERSION_CHECKER_AVAILABLE = False

# Lock file for single instance
LOCK_FILE = "/tmp/docker-status-monitor-test.lock"

def kill_existing_instance():
    """Kill any existing instance of this app."""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            os.kill(old_pid, signal.SIGTERM)
            time.sleep(0.5)
        except (ValueError, ProcessLookupError, PermissionError, FileNotFoundError):
            pass
        try:
            os.remove(LOCK_FILE)
        except FileNotFoundError:
            pass

def create_lock_file():
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))

def remove_lock_file():
    try:
        os.remove(LOCK_FILE)
    except FileNotFoundError:
        pass


class ToolTip:
    """Create a tooltip for a given widget."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)
    
    def show_tooltip(self, event=None):
        if self.tooltip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 25
        
        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                        background="#45475a", foreground="#cdd6f4",
                        relief=tk.SOLID, borderwidth=1,
                        font=("Segoe UI", 9), padx=8, pady=4)
        label.pack()
    
    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


class DockerStatusMonitorWithNotifications:
    # Color scheme
    BG_DARK = "#1e1e2e"
    BG_CARD = "#2a2a3e"
    BG_SIDEBAR = "#252535"
    FG_TEXT = "#cdd6f4"
    FG_DIM = "#6c7086"
    ACCENT_GREEN = "#a6e3a1"
    ACCENT_RED = "#f38ba8"
    ACCENT_BLUE = "#89b4fa"
    ACCENT_YELLOW = "#f9e2af"
    ACCENT_CYAN = "#94e2d5"
    ACCENT_ORANGE = "#fab387"
    
    STATUS_ICONS = {
        "healthy": ("✓", "Healthy - Container is running and health checks pass"),
        "unhealthy": ("⚠", "Unhealthy - Container is running but health checks fail"),
        "running": ("●", "Running - Container is active (no health check defined)"),
        "stack": ("📦", "Stack - Docker Compose project with multiple containers"),
    }
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.tk.call('tk', 'appname', 'docker-status-monitor-test')
        self.root.title("🐳 Docker Status Monitor (TEST)")
        self.root.geometry("500x450")  # Default without sidebar
        self.root.minsize(450, 350)
        self.root.resizable(True, True)
        self.root.configure(bg=self.BG_DARK)
        self.root.attributes('-topmost', True)
        
        # Track collapsed stacks
        self.collapsed_stacks = set()
        self.container_data = {}
        
        # Notification state
        self.update_notifications = []  # List of update results
        self.notification_errors = []   # List of errors
        self.sidebar_visible = False
        self.checking_updates = False
        self.updates_expanded = False  # Whether the update details are shown
        
        # Configure styles
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.style.configure("Treeview", 
                            background=self.BG_CARD,
                            foreground=self.FG_TEXT,
                            fieldbackground=self.BG_CARD,
                            borderwidth=0,
                            rowheight=28,
                            font=("Segoe UI", 10))
        self.style.configure("Treeview.Heading",
                            background=self.BG_DARK,
                            foreground=self.ACCENT_BLUE,
                            font=("Segoe UI", 10, "bold"),
                            borderwidth=0)
        self.style.map("Treeview", background=[("selected", "#45475a")])
        
        # Main container
        self.main_container = tk.Frame(self.root, bg=self.BG_DARK)
        self.main_container.pack(fill=tk.BOTH, expand=True)
        
        # Left panel (main content)
        self.left_panel = tk.Frame(self.main_container, bg=self.BG_DARK)
        self.left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Right panel (notification sidebar) - initially hidden
        # Fixed width of 320px, doesn't expand when window widens
        self.SIDEBAR_WIDTH = 320
        self.right_panel = tk.Frame(self.main_container, bg=self.BG_SIDEBAR, width=self.SIDEBAR_WIDTH)
        # Don't pack yet - will show/hide with toggle
        
        self._setup_header()
        self._setup_legend()
        self._setup_container_list()
        self._setup_footer()
        self._setup_sidebar()
        
        # Start threads
        self.running = True
        self.refresh_thread = threading.Thread(target=self.auto_refresh_loop, daemon=True)
        self.refresh_thread.start()
        
        # Initial refresh
        self.refresh_status()
        
        # Check for updates on startup (in background)
        if VERSION_CHECKER_AVAILABLE:
            self.check_updates_async()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def _setup_header(self):
        self.header_frame = tk.Frame(self.left_panel, bg=self.BG_CARD, pady=12, padx=15)
        self.header_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        self.title_label = tk.Label(self.header_frame, text="🐳 Docker Status Monitor", 
                                    font=("Segoe UI", 14, "bold"), 
                                    bg=self.BG_CARD, fg=self.FG_TEXT)
        self.title_label.pack(side=tk.LEFT)
        
        # Notification bell icon with badge (right side of header)
        self.bell_frame = tk.Frame(self.header_frame, bg=self.BG_CARD, cursor="hand2")
        self.bell_frame.pack(side=tk.RIGHT, padx=(10, 0))
        
        self.bell_label = tk.Label(self.bell_frame, text="🔔", 
                                   font=("Segoe UI", 14),
                                   bg=self.BG_CARD, fg=self.FG_DIM)
        self.bell_label.pack(side=tk.LEFT)
        
        # Badge showing count (hidden when 0)
        self.bell_badge = tk.Label(self.bell_frame, text="", 
                                   font=("Segoe UI", 8, "bold"),
                                   bg=self.ACCENT_ORANGE, fg=self.BG_DARK,
                                   padx=4, pady=0)
        # Badge positioned to overlap bell
        
        # Bind click to toggle sidebar
        self.bell_frame.bind("<Button-1>", lambda e: self.toggle_sidebar())
        self.bell_label.bind("<Button-1>", lambda e: self.toggle_sidebar())
        self.bell_badge.bind("<Button-1>", lambda e: self.toggle_sidebar())
        
        ToolTip(self.bell_frame, "Click to show/hide notifications")
        
        self.status_badge = tk.Label(self.header_frame, text="● CHECKING", 
                                     font=("Segoe UI", 11, "bold"),
                                     bg=self.BG_CARD, fg=self.FG_DIM, padx=10)
        self.status_badge.pack(side=tk.RIGHT)
        
        self.count_badge = tk.Label(self.header_frame, text="0 containers",
                                    font=("Segoe UI", 10),
                                    bg=self.BG_DARK, fg=self.ACCENT_BLUE, padx=8, pady=2)
        self.count_badge.pack(side=tk.RIGHT, padx=10)
    
    def _setup_legend(self):
        self.legend_frame = tk.Frame(self.left_panel, bg=self.BG_DARK, pady=5)
        self.legend_frame.pack(fill=tk.X, padx=15)
        
        legend_items = [
            ("✓", self.ACCENT_GREEN, "Healthy"),
            ("●", self.FG_TEXT, "Running"),
            ("⚠", self.ACCENT_YELLOW, "Unhealthy"),
            ("📦", self.ACCENT_CYAN, "Stack"),
        ]
        
        for icon, color, label in legend_items:
            item_frame = tk.Frame(self.legend_frame, bg=self.BG_DARK)
            item_frame.pack(side=tk.LEFT, padx=6)
            tk.Label(item_frame, text=icon, font=("Segoe UI", 10), bg=self.BG_DARK, fg=color).pack(side=tk.LEFT)
            tk.Label(item_frame, text=label, font=("Segoe UI", 9), bg=self.BG_DARK, fg=self.FG_DIM).pack(side=tk.LEFT, padx=(2, 0))
    
    def _setup_container_list(self):
        self.list_frame = tk.Frame(self.left_panel, bg=self.BG_DARK)
        self.list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))
        
        columns = ("name", "uptime", "ports")
        self.tree = ttk.Treeview(self.list_frame, columns=columns, show="headings", height=8)
        self.tree.heading("name", text="Container / Stack")
        self.tree.heading("uptime", text="Uptime")
        self.tree.heading("ports", text="Ports")
        self.tree.column("name", width=200, stretch=True)
        self.tree.column("uptime", width=80, stretch=False)
        self.tree.column("ports", width=120, stretch=True)
        
        self.tree.bind("<Motion>", self.on_tree_motion)
        self.tree.bind("<Leave>", self.on_tree_leave)
        self.tree.bind("<Button-1>", self.on_tree_click)
        
        self.tree.tag_configure("healthy", foreground=self.ACCENT_GREEN)
        self.tree.tag_configure("running", foreground=self.FG_TEXT)
        self.tree.tag_configure("unhealthy", foreground=self.ACCENT_YELLOW)
        self.tree.tag_configure("stack_healthy", foreground=self.ACCENT_CYAN, font=("Segoe UI", 10, "bold"))
        self.tree.tag_configure("stack_unhealthy", foreground=self.ACCENT_YELLOW, font=("Segoe UI", 10, "bold"))
        self.tree.tag_configure("stack_running", foreground=self.ACCENT_CYAN, font=("Segoe UI", 10, "bold"))
        self.tree.tag_configure("child_healthy", foreground=self.ACCENT_GREEN)
        self.tree.tag_configure("child_running", foreground=self.FG_TEXT)
        self.tree.tag_configure("child_unhealthy", foreground=self.ACCENT_YELLOW)
        
        scrollbar = ttk.Scrollbar(self.list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree_tooltip = None
    
    def _setup_footer(self):
        self.footer_frame = tk.Frame(self.left_panel, bg=self.BG_DARK, pady=8)
        self.footer_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 8))
        
        self.refresh_btn = tk.Button(self.footer_frame, text="⟳ Refresh", 
                                     command=self.refresh_status,
                                     font=("Segoe UI", 10),
                                     bg=self.ACCENT_BLUE, fg=self.BG_DARK,
                                     activebackground="#7aa2f7",
                                     border=0, padx=12, pady=4, cursor="hand2")
        self.refresh_btn.pack(side=tk.LEFT)
        
        self.auto_refresh_var = tk.BooleanVar(value=True)
        self.auto_refresh_cb = tk.Checkbutton(self.footer_frame, text="Auto-refresh",
                                              variable=self.auto_refresh_var,
                                              font=("Segoe UI", 9),
                                              bg=self.BG_DARK, fg=self.FG_DIM,
                                              selectcolor=self.BG_CARD,
                                              activebackground=self.BG_DARK)
        self.auto_refresh_cb.pack(side=tk.LEFT, padx=10)
        
        self.always_on_top_var = tk.BooleanVar(value=True)
        self.always_on_top_cb = tk.Checkbutton(self.footer_frame, text="On Top",
                                               variable=self.always_on_top_var,
                                               command=self.toggle_always_on_top,
                                               font=("Segoe UI", 9),
                                               bg=self.BG_DARK, fg=self.FG_DIM,
                                               selectcolor=self.BG_CARD,
                                               activebackground=self.BG_DARK)
        self.always_on_top_cb.pack(side=tk.LEFT, padx=5)
        
        self.updated_label = tk.Label(self.footer_frame, text="",
                                      font=("Segoe UI", 9),
                                      bg=self.BG_DARK, fg=self.FG_DIM)
        self.updated_label.pack(side=tk.RIGHT)
    
    def _setup_sidebar(self):
        """Setup the notification sidebar (initially hidden)."""
        self.right_panel.pack_propagate(False)
        
        # Sidebar header
        sidebar_header = tk.Frame(self.right_panel, bg=self.BG_SIDEBAR, pady=12)
        sidebar_header.pack(fill=tk.X, padx=15)
        
        tk.Label(sidebar_header, text="🔔 Notifications", 
                font=("Segoe UI", 12, "bold"),
                bg=self.BG_SIDEBAR, fg=self.FG_TEXT).pack(side=tk.LEFT)
        
        # Close button
        close_btn = tk.Label(sidebar_header, text="✕", 
                            font=("Segoe UI", 12),
                            bg=self.BG_SIDEBAR, fg=self.FG_DIM, cursor="hand2")
        close_btn.pack(side=tk.RIGHT)
        close_btn.bind("<Button-1>", lambda e: self.toggle_sidebar())
        
        # Separator
        tk.Frame(self.right_panel, bg=self.FG_DIM, height=1).pack(fill=tk.X, padx=10, pady=5)
        
        # Notification list (scrollable)
        self.notification_canvas = tk.Canvas(self.right_panel, bg=self.BG_SIDEBAR, 
                                             highlightthickness=0)
        self.notification_scrollbar = ttk.Scrollbar(self.right_panel, orient=tk.VERTICAL, 
                                                    command=self.notification_canvas.yview)
        self.notification_frame = tk.Frame(self.notification_canvas, bg=self.BG_SIDEBAR)
        
        self.notification_canvas.configure(yscrollcommand=self.notification_scrollbar.set)
        
        self.notification_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.notification_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=5)
        
        self.notification_window = self.notification_canvas.create_window((0, 0), 
                                                                          window=self.notification_frame, 
                                                                          anchor="nw")
        
        self.notification_frame.bind("<Configure>", self._on_notification_frame_configure)
        self.notification_canvas.bind("<Configure>", self._on_canvas_configure)
        
        # Bind mouse wheel to scroll the notification canvas
        self.notification_canvas.bind("<Enter>", self._bind_mousewheel)
        self.notification_canvas.bind("<Leave>", self._unbind_mousewheel)
        self.notification_frame.bind("<Enter>", self._bind_mousewheel)
        self.notification_frame.bind("<Leave>", self._unbind_mousewheel)
        
        # Footer with check button and last checked time - PACK BEFORE notification list
        sidebar_footer = tk.Frame(self.right_panel, bg=self.BG_SIDEBAR, pady=10)
        sidebar_footer.pack(side=tk.BOTTOM, fill=tk.X, padx=15)
        
        # Separator above footer
        tk.Frame(self.right_panel, bg=self.FG_DIM, height=1).pack(side=tk.BOTTOM, fill=tk.X, padx=10)
        
        self.check_updates_btn = tk.Button(sidebar_footer, text="🔄 Check Again",
                                           command=lambda: self.check_updates_async(force=True),
                                           font=("Segoe UI", 10),
                                           bg=self.ACCENT_BLUE, fg=self.BG_DARK,
                                           activebackground="#7aa2f7",
                                           border=0, padx=12, pady=6, cursor="hand2")
        self.check_updates_btn.pack(fill=tk.X)
        
        self.last_checked_label = tk.Label(sidebar_footer, text="",
                                           font=("Segoe UI", 8),
                                           bg=self.BG_SIDEBAR, fg=self.FG_DIM)
        self.last_checked_label.pack(anchor="center", pady=(5, 0))
    
    def _on_notification_frame_configure(self, event):
        self.notification_canvas.configure(scrollregion=self.notification_canvas.bbox("all"))
    
    def _on_canvas_configure(self, event):
        self.notification_canvas.itemconfig(self.notification_window, width=event.width)
    
    def _bind_mousewheel(self, event):
        """Bind mouse wheel to notification canvas when mouse enters."""
        self.notification_canvas.bind_all("<Button-4>", self._on_mousewheel_up)
        self.notification_canvas.bind_all("<Button-5>", self._on_mousewheel_down)
        # Windows/MacOS
        self.notification_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
    
    def _unbind_mousewheel(self, event):
        """Unbind mouse wheel when mouse leaves notification area."""
        self.notification_canvas.unbind_all("<Button-4>")
        self.notification_canvas.unbind_all("<Button-5>")
        self.notification_canvas.unbind_all("<MouseWheel>")
    
    def _on_mousewheel_up(self, event):
        """Scroll up on Linux (Button-4)."""
        self.notification_canvas.yview_scroll(-1, "units")
    
    def _on_mousewheel_down(self, event):
        """Scroll down on Linux (Button-5)."""
        self.notification_canvas.yview_scroll(1, "units")
    
    def _on_mousewheel(self, event):
        """Scroll on Windows/MacOS."""
        self.notification_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
    
    def toggle_sidebar(self):
        """Toggle the notification sidebar visibility."""
        if self.sidebar_visible:
            self.right_panel.pack_forget()
            self.root.geometry("500x450")
            self.sidebar_visible = False
        else:
            self.right_panel.pack(side=tk.RIGHT, fill=tk.Y)
            self.root.geometry("850x500")
            self.sidebar_visible = True
    
    def update_bell_badge(self):
        """Update the notification bell badge count."""
        count = len(self.update_notifications)
        
        if count > 0:
            self.bell_badge.config(text=str(count))
            self.bell_badge.pack(side=tk.LEFT, padx=(0, 0))
            self.bell_label.config(fg=self.ACCENT_ORANGE)
        else:
            self.bell_badge.pack_forget()
            self.bell_label.config(fg=self.ACCENT_GREEN if VERSION_CHECKER_AVAILABLE else self.FG_DIM)
    
    def check_updates_async(self, force=False):
        """Check for updates in a background thread."""
        if self.checking_updates or not VERSION_CHECKER_AVAILABLE:
            return
        
        self.checking_updates = True
        self.last_checked_label.config(text="Checking for updates...")
        self.check_updates_btn.config(state=tk.DISABLED, text="⏳ Checking...")
        
        def check_thread():
            try:
                # Import check_all_updates with force option
                from version_checker import check_all_updates as check_updates_func
                
                if force:
                    # Clear the cache by accessing the module's globals
                    import version_checker
                    version_checker._version_cache.clear()
                    version_checker._last_check_time = None
                
                updates, up_to_date, errors = get_updates_with_notifications()
                self.root.after(0, lambda: self.update_notifications_display(updates, errors))
            except Exception as e:
                self.root.after(0, lambda: self.last_checked_label.config(text=f"Error: {str(e)[:30]}"))
            finally:
                self.checking_updates = False
                self.root.after(0, lambda: self.check_updates_btn.config(state=tk.NORMAL, text="🔄 Check Again"))
        
        threading.Thread(target=check_thread, daemon=True).start()
    
    def update_notifications_display(self, updates, errors):
        """Update the notification data and refresh display."""
        self.update_notifications = updates
        self.notification_errors = errors
        self.updates_expanded = False
        
        # Update badge
        self.update_bell_badge()
        
        # Update last checked time
        last_check = get_last_check_time()
        if last_check:
            self.last_checked_label.config(text=f"Last checked: {last_check.strftime('%H:%M')}")
        
        # Refresh the notification list
        self.refresh_notification_list()
    
    def refresh_notification_list(self):
        """Refresh the notification list in the sidebar."""
        # Clear existing notifications
        for widget in self.notification_frame.winfo_children():
            widget.destroy()
        
        total_notifications = len(self.update_notifications) + (1 if self.notification_errors else 0)
        
        if total_notifications == 0:
            # All good message
            all_good_frame = tk.Frame(self.notification_frame, bg=self.BG_SIDEBAR, pady=20)
            all_good_frame.pack(fill=tk.X)
            tk.Label(all_good_frame, text="✓", font=("Segoe UI", 24),
                    bg=self.BG_SIDEBAR, fg=self.ACCENT_GREEN).pack()
            tk.Label(all_good_frame, text="All containers up to date!",
                    font=("Segoe UI", 10),
                    bg=self.BG_SIDEBAR, fg=self.ACCENT_GREEN).pack()
            return
        
        # Container Updates notification (consolidated)
        if self.update_notifications:
            self._add_updates_notification()
        
        # Errors notification (if any)
        if self.notification_errors:
            self._add_errors_notification()
    
    def _add_updates_notification(self):
        """Add the consolidated updates notification."""
        count = len(self.update_notifications)
        
        # Main notification card
        card = tk.Frame(self.notification_frame, bg=self.BG_CARD, padx=10, pady=10)
        card.pack(fill=tk.X, pady=(5, 5))
        
        # Header row (clickable to expand)
        header = tk.Frame(card, bg=self.BG_CARD, cursor="hand2")
        header.pack(fill=tk.X)
        
        # Expand/collapse indicator
        self.updates_expand_label = tk.Label(header, 
                                             text="▼" if self.updates_expanded else "▶",
                                             font=("Segoe UI", 10),
                                             bg=self.BG_CARD, fg=self.FG_DIM)
        self.updates_expand_label.pack(side=tk.LEFT)
        
        # Icon
        tk.Label(header, text="⬆️", font=("Segoe UI", 12),
                bg=self.BG_CARD, fg=self.ACCENT_ORANGE).pack(side=tk.LEFT, padx=(5, 5))
        
        # Title
        tk.Label(header, text=f"Container Updates Available",
                font=("Segoe UI", 10, "bold"),
                bg=self.BG_CARD, fg=self.FG_TEXT).pack(side=tk.LEFT)
        
        # Count badge
        tk.Label(header, text=str(count),
                font=("Segoe UI", 9, "bold"),
                bg=self.ACCENT_ORANGE, fg=self.BG_DARK,
                padx=6, pady=1).pack(side=tk.RIGHT)
        
        # Bind click to expand/collapse
        for widget in [header, self.updates_expand_label]:
            widget.bind("<Button-1>", lambda e: self.toggle_updates_expanded())
        
        # Expanded content (version details)
        if self.updates_expanded:
            self._add_expanded_update_details(card)
    
    def _add_expanded_update_details(self, parent):
        """Add the expanded version comparison details."""
        # Separator
        tk.Frame(parent, bg=self.FG_DIM, height=1).pack(fill=tk.X, pady=(10, 5))
        
        # Subtitle
        tk.Label(parent, text="Not running latest version:",
                font=("Segoe UI", 9),
                bg=self.BG_CARD, fg=self.FG_DIM).pack(anchor="w", pady=(0, 5))
        
        # List each update
        for update in self.update_notifications:
            self._add_update_detail_row(parent, update)
    
    def _add_update_detail_row(self, parent, update):
        """Add a single update detail row showing version comparison."""
        # Calculate wrap length based on sidebar width (minus padding)
        wrap_len = self.SIDEBAR_WIDTH - 80
        
        row = tk.Frame(parent, bg=self.BG_CARD, pady=6)
        row.pack(fill=tk.X)
        
        # Extract info
        project = update.get('project', 'Unknown')
        service = update.get('service', '')
        image = update.get('image', 'unknown')
        tag = update.get('tag', 'latest')
        is_pinned = update.get('pinned_version', False)
        registry = update.get('registry', 'Registry')
        last_updated = update.get('last_updated', '')  # Remote publish date
        local_created = update.get('local_created', '')  # Local image date
        local_version = update.get('local_version', '')  # Detected local version
        latest_version = update.get('latest_version', '')  # Latest available version
        
        # Icon based on pinned status
        icon = "📌" if is_pinned else "⬆️"
        icon_color = self.ACCENT_YELLOW if is_pinned else self.ACCENT_ORANGE
        
        # Header line: Icon + Project name
        header = tk.Frame(row, bg=self.BG_CARD)
        header.pack(fill=tk.X)
        
        tk.Label(header, text=icon, font=("Segoe UI", 10),
                bg=self.BG_CARD, fg=icon_color).pack(side=tk.LEFT)
        tk.Label(header, text=f" {project}",
                font=("Segoe UI", 10, "bold"),
                bg=self.BG_CARD, fg=self.FG_TEXT).pack(side=tk.LEFT)
        
        # Update button (right side of header)
        if is_pinned:
            # Greyed out button for pinned versions
            update_btn = tk.Label(header, text="🔒",
                                 font=("Segoe UI", 10),
                                 bg=self.BG_CARD, fg=self.FG_DIM,
                                 cursor="question_arrow")
            update_btn.pack(side=tk.RIGHT, padx=(5, 0))
            # Tooltip for pinned
            update_btn.bind("<Enter>", lambda e, t=tag: self._show_pinned_tooltip(e, t))
            update_btn.bind("<Leave>", lambda e: self._hide_tooltip())
        else:
            # Active update button
            update_btn = tk.Button(header, text="⬆ Update",
                                  font=("Segoe UI", 8),
                                  bg=self.ACCENT_GREEN, fg=self.BG_DARK,
                                  activebackground="#a6e3a1",
                                  border=0, padx=6, pady=2, cursor="hand2",
                                  command=lambda p=project: self.update_container(p))
            update_btn.pack(side=tk.RIGHT, padx=(5, 0))
        
        # Image name on next line (full name, wrapped)
        image_short = image.split('/')[-1] if '/' in image else image
        tk.Label(row, text=f"  {image_short}:{tag}",
                font=("Segoe UI", 9),
                bg=self.BG_CARD, fg=self.FG_DIM,
                wraplength=wrap_len, justify="left", anchor="w").pack(fill=tk.X, anchor="w")
        
        # Details frame (indented)
        details = tk.Frame(row, bg=self.BG_CARD)
        details.pack(fill=tk.X, padx=(10, 0), pady=(4, 0))
        
        # Check if we have version info (from tag matching)
        if local_version and latest_version:
            # Show version comparison
            tk.Label(details, text=f"Running: {local_version}",
                    font=("Segoe UI", 9),
                    bg=self.BG_CARD, fg=self.FG_TEXT).pack(anchor="w")
            tk.Label(details, text=f"Latest:  {latest_version}",
                    font=("Segoe UI", 9, "bold"),
                    bg=self.BG_CARD, fg=self.ACCENT_ORANGE).pack(anchor="w")
        else:
            # Fallback to date comparison
            local_date = local_created if local_created else "Unknown"
            remote_date = last_updated[:10] if last_updated else "Unknown"
            
            dates_same = (local_date == remote_date) or (local_date == "Unknown" or remote_date == "Unknown")
            
            tk.Label(details, text=f"Your image: {local_date}",
                    font=("Segoe UI", 9),
                    bg=self.BG_CARD, fg=self.FG_TEXT).pack(anchor="w")
            
            if dates_same:
                tk.Label(details, text="Newer build available",
                        font=("Segoe UI", 9, "bold"),
                        bg=self.BG_CARD, fg=self.ACCENT_ORANGE,
                        wraplength=wrap_len, justify="left").pack(anchor="w")
            else:
                tk.Label(details, text=f"Latest: {remote_date}",
                        font=("Segoe UI", 9, "bold"),
                        bg=self.BG_CARD, fg=self.ACCENT_ORANGE).pack(anchor="w")
                
                # Calculate how far behind
                if local_created and last_updated:
                    try:
                        from datetime import datetime
                        local_dt = datetime.strptime(local_created, "%Y-%m-%d")
                        remote_dt = datetime.strptime(remote_date, "%Y-%m-%d")
                        days_behind = (remote_dt - local_dt).days
                        
                        if days_behind > 0:
                            if days_behind == 1:
                                behind_text = "1 day behind"
                            elif days_behind < 30:
                                behind_text = f"{days_behind} days behind"
                            elif days_behind < 365:
                                months = days_behind // 30
                                behind_text = f"~{months} month{'s' if months > 1 else ''} behind"
                            else:
                                years = days_behind // 365
                                behind_text = f"~{years} year{'s' if years > 1 else ''} behind"
                            
                            tk.Label(details, text=f"⚠ {behind_text}",
                                    font=("Segoe UI", 8, "bold"),
                                    bg=self.BG_CARD, fg=self.ACCENT_ORANGE).pack(anchor="w")
                    except:
                        pass
        
        # Pinned version warning
        if is_pinned:
            tk.Label(details, text=f"📌 Pinned to :{tag} in docker-compose",
                    font=("Segoe UI", 8),
                    bg=self.BG_CARD, fg=self.ACCENT_YELLOW,
                    wraplength=wrap_len, justify="left").pack(anchor="w", pady=(2, 0))
    
    def _show_pinned_tooltip(self, event, tag):
        """Show tooltip for pinned version."""
        self._show_tooltip(event, f"Cannot update: pinned to :{tag}\nEdit docker-compose.yml to change version")
    
    def _show_tooltip(self, event, text):
        """Show a tooltip at the cursor position."""
        self._hide_tooltip()
        x, y = event.x_root + 10, event.y_root + 10
        self.update_tooltip = tw = tk.Toplevel(self.root)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=text, justify=tk.LEFT,
                        background="#45475a", foreground="#cdd6f4",
                        relief=tk.SOLID, borderwidth=1,
                        font=("Segoe UI", 9), padx=8, pady=4)
        label.pack()
    
    def _hide_tooltip(self):
        """Hide the tooltip."""
        if hasattr(self, 'update_tooltip') and self.update_tooltip:
            self.update_tooltip.destroy()
            self.update_tooltip = None
    
    def update_container(self, project_name):
        """Update a container by pulling latest and recreating - runs in visible terminal."""
        # Find the project folder
        workspace = Path(__file__).parent.parent.parent
        project_path = workspace / project_name
        compose_file = project_path / "docker-compose.yml"
        
        if not compose_file.exists():
            self._show_update_result(project_name, False, "docker-compose.yml not found")
            return
        
        # Build the update script to run in terminal
        # IMPORTANT: No 'down -v' - we preserve data!
        script = f'''
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  Docker Status Monitor - Container Update                  ║"
echo "║  Project: {project_name:<48} ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "📁 Working directory:"
echo "   {project_path}"
echo ""
cd "{project_path}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📥 Step 1: Pulling latest images..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
docker compose pull
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔄 Step 2: Recreating container (preserving data)..."
echo "   Command: docker compose up -d --force-recreate"
echo "   ⚠️  NOT using 'down -v' - volumes are preserved!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
docker compose up -d --force-recreate
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Update complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Press Enter to close this terminal..."
read
'''
        
        # Try different terminal emulators
        terminals = [
            # GNOME Terminal
            ["gnome-terminal", "--", "bash", "-c", script],
            # Konsole (KDE)
            ["konsole", "-e", "bash", "-c", script],
            # xfce4-terminal
            ["xfce4-terminal", "-e", f"bash -c '{script}'"],
            # xterm (fallback)
            ["xterm", "-e", f"bash -c '{script}'"],
        ]
        
        import subprocess
        import shutil
        
        for term_cmd in terminals:
            term_name = term_cmd[0]
            if shutil.which(term_name):
                try:
                    subprocess.Popen(term_cmd, start_new_session=True)
                    
                    # Schedule a refresh after update likely completes
                    self.root.after(10000, self.refresh_status)
                    self.root.after(12000, lambda: self.check_updates_async(force=True))
                    return
                except Exception as e:
                    continue
        
        # Fallback: run in background if no terminal found
        self._show_update_result(project_name, False, 
            "No terminal emulator found. Install gnome-terminal, konsole, or xterm.")
        
        # Start update thread
        import threading
        threading.Thread(target=do_update, daemon=True).start()
    
    def _update_status(self, project_name, status):
        """Update the status shown during container update."""
        # This runs in a thread, so schedule UI update
        self.root.after(0, lambda: self._show_update_progress(project_name, status))
    
    def _show_update_progress(self, project_name, status):
        """Show update progress in the sidebar."""
        # For now, just update the window title
        self.root.title(f"Docker Status Monitor (TEST) - {project_name}: {status}")
    
    def _show_update_result(self, project_name, success, message):
        """Show the result of an update attempt."""
        self.root.title("Docker Status Monitor (TEST)")
        
        if success:
            # Show success notification
            icon = "✅"
            color = self.ACCENT_GREEN
        else:
            icon = "❌"
            color = self.ACCENT_RED
        
        # Create a popup notification
        popup = tk.Toplevel(self.root)
        popup.title("Update Result")
        popup.geometry("350x120")
        popup.configure(bg=self.BG_CARD)
        popup.transient(self.root)
        popup.grab_set()
        
        # Center on parent
        popup.geometry(f"+{self.root.winfo_x() + 75}+{self.root.winfo_y() + 150}")
        
        tk.Label(popup, text=f"{icon} {project_name}",
                font=("Segoe UI", 12, "bold"),
                bg=self.BG_CARD, fg=color).pack(pady=(15, 5))
        
        tk.Label(popup, text=message,
                font=("Segoe UI", 10),
                bg=self.BG_CARD, fg=self.FG_TEXT,
                wraplength=300).pack(pady=5)
        
        tk.Button(popup, text="OK", command=popup.destroy,
                 font=("Segoe UI", 10),
                 bg=self.ACCENT_BLUE, fg=self.BG_DARK,
                 border=0, padx=20, pady=5).pack(pady=10)
    
    def _add_errors_notification(self):
        """Add errors notification."""
        count = len(self.notification_errors)
        wrap_len = self.SIDEBAR_WIDTH - 80
        
        card = tk.Frame(self.notification_frame, bg=self.BG_CARD, padx=10, pady=8)
        card.pack(fill=tk.X, pady=(0, 5))
        
        header = tk.Frame(card, bg=self.BG_CARD)
        header.pack(fill=tk.X)
        
        tk.Label(header, text="⚠️", font=("Segoe UI", 10),
                bg=self.BG_CARD, fg=self.ACCENT_YELLOW).pack(side=tk.LEFT)
        tk.Label(header, text=f" {count} could not be checked",
                font=("Segoe UI", 9),
                bg=self.BG_CARD, fg=self.FG_DIM,
                wraplength=wrap_len-30, justify="left").pack(side=tk.LEFT)
    
    def toggle_updates_expanded(self):
        """Toggle the expanded state of updates notification."""
        self.updates_expanded = not self.updates_expanded
        self.refresh_notification_list()
    
    # Container list functionality (unchanged from original)
    
    def on_tree_motion(self, event):
        item = self.tree.identify_row(event.y)
        if item and item in self.container_data:
            data = self.container_data[item]
            if data.get("status_type") == "stack":
                tooltip_text = f"Stack: {data.get('name', 'Unknown')}\n{data.get('full_status', '')}"
            else:
                tooltip_text = f"Container: {data.get('name', 'Unknown')}\nStatus: {data.get('full_status', 'Unknown')}"
                if data.get('stack'):
                    tooltip_text += f"\nStack: {data.get('stack')}"
                tooltip_text += f"\nUptime: {data.get('uptime', 'Unknown')}"
            self.show_tree_tooltip(event, tooltip_text)
        else:
            self.hide_tree_tooltip()
    
    def on_tree_leave(self, event):
        self.hide_tree_tooltip()
    
    def show_tree_tooltip(self, event, text):
        if self.tree_tooltip:
            self.tree_tooltip.destroy()
        x, y = event.x_root + 15, event.y_root + 10
        self.tree_tooltip = tw = tk.Toplevel(self.root)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=text, justify=tk.LEFT,
                        background="#45475a", foreground="#cdd6f4",
                        relief=tk.SOLID, borderwidth=1,
                        font=("Segoe UI", 9), padx=8, pady=4)
        label.pack()
    
    def hide_tree_tooltip(self):
        if self.tree_tooltip:
            self.tree_tooltip.destroy()
            self.tree_tooltip = None
    
    def on_tree_click(self, event):
        item = self.tree.identify_row(event.y)
        if item and item.startswith("stack_"):
            stack_name = item.replace("stack_", "")
            if stack_name in self.collapsed_stacks:
                self.collapsed_stacks.remove(stack_name)
            else:
                self.collapsed_stacks.add(stack_name)
            self.refresh_status()
    
    def toggle_always_on_top(self):
        self.root.attributes('-topmost', self.always_on_top_var.get())
    
    def is_docker_running(self):
        try:
            result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
            return result.returncode == 0
        except:
            return False
    
    def get_containers(self):
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", 
                 "{{.Names}}|{{.Status}}|{{.Ports}}|{{.RunningFor}}|{{.Label \"com.docker.compose.project\"}}"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                containers = []
                for line in result.stdout.strip().split("\n"):
                    parts = line.split("|")
                    if len(parts) >= 2:
                        ports = parts[2] if len(parts) > 2 else ""
                        uptime = parts[3] if len(parts) > 3 else ""
                        stack = parts[4] if len(parts) > 4 else ""
                        uptime_display = uptime.replace("About ", "~").replace(" ago", "")
                        simple_ports = []
                        for p in ports.split(", "):
                            if "->" in p:
                                try:
                                    mapping = p.split("->")
                                    host_part = mapping[0].split(":")[-1]
                                    simple_ports.append(f"{host_part}")
                                except:
                                    pass
                        containers.append({
                            "name": parts[0], 
                            "status": parts[1],
                            "full_status": parts[1],
                            "uptime": uptime_display,
                            "uptime_full": uptime,
                            "ports": ", ".join(simple_ports) if simple_ports else "—",
                            "stack": stack.strip() if stack.strip() else None
                        })
                return containers
            return []
        except:
            return []
    
    def group_containers_by_stack(self, containers):
        stacks = {}
        standalone = []
        for container in containers:
            stack_name = container.get("stack")
            if stack_name:
                if stack_name not in stacks:
                    stacks[stack_name] = []
                stacks[stack_name].append(container)
            else:
                standalone.append(container)
        return stacks, standalone
    
    def get_stack_status(self, containers):
        has_unhealthy = any("unhealthy" in c["status"].lower() for c in containers)
        has_healthy = any("healthy" in c["status"].lower() and "unhealthy" not in c["status"].lower() for c in containers)
        if has_unhealthy:
            return "unhealthy"
        elif has_healthy:
            return "healthy"
        return "running"
    
    def refresh_status(self):
        if self.is_docker_running():
            self.status_badge.config(text="● RUNNING", fg=self.ACCENT_GREEN)
        else:
            self.status_badge.config(text="● STOPPED", fg=self.ACCENT_RED)
        
        self.container_data = {}
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        containers = self.get_containers()
        stacks, standalone = self.group_containers_by_stack(containers)
        
        for stack_name in sorted(stacks.keys()):
            stack_containers = stacks[stack_name]
            
            if len(stack_containers) == 1:
                container = stack_containers[0]
                status = container["status"].lower()
                if "healthy" in status and "unhealthy" not in status:
                    icon, tag, status_type = self.STATUS_ICONS["healthy"][0], "healthy", "healthy"
                elif "unhealthy" in status:
                    icon, tag, status_type = self.STATUS_ICONS["unhealthy"][0], "unhealthy", "unhealthy"
                else:
                    icon, tag, status_type = self.STATUS_ICONS["running"][0], "running", "running"
                
                item_id = f"single_{container['name']}"
                self.tree.insert("", tk.END, iid=item_id,
                               values=(f"{icon}  {container['name']}", container["uptime"], container["ports"]),
                               tags=(tag,))
                self.container_data[item_id] = {"name": container["name"], "status_type": status_type,
                                                "full_status": container["full_status"], "stack": stack_name,
                                                "uptime": container["uptime_full"]}
                continue
            
            is_collapsed = stack_name in self.collapsed_stacks
            stack_status = self.get_stack_status(stack_containers)
            stack_icon = self.STATUS_ICONS.get(stack_status, ("●", ""))[0]
            expand_indicator = "▶" if is_collapsed else "▼"
            
            stack_id = f"stack_{stack_name}"
            self.tree.insert("", tk.END, iid=stack_id,
                           values=(f"{expand_indicator} 📦 {stack_icon}  {stack_name} ({len(stack_containers)})", "", ""),
                           tags=(f"stack_{stack_status}",))
            self.container_data[stack_id] = {"name": stack_name, "status_type": "stack",
                                             "full_status": f"Stack with {len(stack_containers)} containers ({stack_status})\nClick to {'expand' if is_collapsed else 'collapse'}",
                                             "stack": stack_name, "uptime": ""}
            
            if not is_collapsed:
                sorted_containers = sorted(stack_containers, key=lambda x: x["name"])
                for i, container in enumerate(sorted_containers):
                    status = container["status"].lower()
                    if "healthy" in status and "unhealthy" not in status:
                        icon, status_type = self.STATUS_ICONS["healthy"][0], "healthy"
                    elif "unhealthy" in status:
                        icon, status_type = self.STATUS_ICONS["unhealthy"][0], "unhealthy"
                    else:
                        icon, status_type = self.STATUS_ICONS["running"][0], "running"
                    
                    is_last = (i == len(sorted_containers) - 1)
                    prefix = "    └─" if is_last else "    ├─"
                    
                    item_id = f"container_{container['name']}"
                    self.tree.insert("", tk.END, iid=item_id,
                                   values=(f"{prefix} {icon}  {container['name']}", container["uptime"], container["ports"]),
                                   tags=(f"child_{status_type}",))
                    self.container_data[item_id] = {"name": container["name"], "status_type": status_type,
                                                    "full_status": container["full_status"], "stack": stack_name,
                                                    "uptime": container["uptime_full"]}
        
        for container in sorted(standalone, key=lambda x: x["name"]):
            status = container["status"].lower()
            if "healthy" in status and "unhealthy" not in status:
                icon, tag, status_type = self.STATUS_ICONS["healthy"][0], "healthy", "healthy"
            elif "unhealthy" in status:
                icon, tag, status_type = self.STATUS_ICONS["unhealthy"][0], "unhealthy", "unhealthy"
            else:
                icon, tag, status_type = self.STATUS_ICONS["running"][0], "running", "running"
            
            item_id = f"standalone_{container['name']}"
            self.tree.insert("", tk.END, iid=item_id,
                           values=(f"{icon}  {container['name']}", container["uptime"], container["ports"]),
                           tags=(tag,))
            self.container_data[item_id] = {"name": container["name"], "status_type": status_type,
                                            "full_status": container["full_status"], "stack": None,
                                            "uptime": container["uptime_full"]}
        
        self.count_badge.config(text=f"{len(containers)} container{'s' if len(containers) != 1 else ''}")
        self.updated_label.config(text=f"Updated: {time.strftime('%H:%M:%S')}")
    
    def auto_refresh_loop(self):
        update_check_counter = 0
        while self.running:
            time.sleep(5)
            if self.running and self.auto_refresh_var.get():
                self.root.after(0, self.refresh_status)
            
            # Check for updates every 24 hours (24*60*60 / 5 = 17280 iterations)
            update_check_counter += 1
            if update_check_counter >= 17280 and VERSION_CHECKER_AVAILABLE:
                update_check_counter = 0
                self.root.after(0, self.check_updates_async)
    
    def on_close(self):
        self.running = False
        remove_lock_file()
        self.root.destroy()
    
    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    kill_existing_instance()
    create_lock_file()
    
    import atexit
    atexit.register(remove_lock_file)
    
    app = DockerStatusMonitorWithNotifications()
    app.run()
