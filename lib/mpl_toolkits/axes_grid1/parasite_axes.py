import functools

from matplotlib import _api, cbook
import matplotlib.artist as martist
import matplotlib.transforms as mtransforms
from matplotlib.axes import subplot_class_factory
from matplotlib.transforms import Bbox
from .mpl_axes import Axes


class ParasiteAxesBase:

    def get_images_artists(self):
        artists = {a for a in self.get_children() if a.get_visible()}
        images = {a for a in self.images if a.get_visible()}
        return list(images), list(artists - images)

    def __init__(self, parent_axes, **kwargs):
        self._parent_axes = parent_axes
        kwargs["frameon"] = False
        super().__init__(parent_axes.figure, parent_axes._position, **kwargs)

    def cla(self):
        super().cla()
        martist.setp(self.get_children(), visible=False)
        self._get_lines = self._parent_axes._get_lines

    def pick(self, mouseevent):
        # This most likely goes to Artist.pick (depending on axes_class given
        # to the factory), which only handles pick events registered on the
        # axes associated with each child:
        super().pick(mouseevent)
        # But parasite axes are additionally given pick events from their host
        # axes (cf. HostAxesBase.pick), which we handle here:
        for a in self.get_children():
            if (hasattr(mouseevent.inaxes, "parasites")
                    and self in mouseevent.inaxes.parasites):
                a.pick(mouseevent)


@functools.lru_cache(None)
def parasite_axes_class_factory(axes_class=None):
    if axes_class is None:
        cbook.warn_deprecated(
            "3.3", message="Support for passing None to "
            "parasite_axes_class_factory is deprecated since %(since)s and "
            "will be removed %(removal)s; explicitly pass the default Axes "
            "class instead.")
        axes_class = Axes

    return type("%sParasite" % axes_class.__name__,
                (ParasiteAxesBase, axes_class), {})


ParasiteAxes = parasite_axes_class_factory(Axes)


class ParasiteAxesAuxTransBase:
    def __init__(self, parent_axes, aux_transform, viewlim_mode=None,
                 **kwargs):
        self.transAux = aux_transform
        self.set_viewlim_mode(viewlim_mode)
        super().__init__(parent_axes, **kwargs)

    def _set_lim_and_transforms(self):
        self.transAxes = self._parent_axes.transAxes
        self.transData = self.transAux + self._parent_axes.transData
        self._xaxis_transform = mtransforms.blended_transform_factory(
            self.transData, self.transAxes)
        self._yaxis_transform = mtransforms.blended_transform_factory(
            self.transAxes, self.transData)

    def set_viewlim_mode(self, mode):
        _api.check_in_list([None, "equal", "transform"], mode=mode)
        self._viewlim_mode = mode

    def get_viewlim_mode(self):
        return self._viewlim_mode

    @cbook.deprecated("3.4", alternative="apply_aspect")
    def update_viewlim(self):
        return self._update_viewlim()

    def _update_viewlim(self):  # Inline after deprecation elapses.
        viewlim = self._parent_axes.viewLim.frozen()
        mode = self.get_viewlim_mode()
        if mode is None:
            pass
        elif mode == "equal":
            self.axes.viewLim.set(viewlim)
        elif mode == "transform":
            self.axes.viewLim.set(
                viewlim.transformed(self.transAux.inverted()))
        else:
            _api.check_in_list([None, "equal", "transform"], mode=mode)

    def apply_aspect(self, position=None):
        self._update_viewlim()
        super().apply_aspect()


@functools.lru_cache(None)
def parasite_axes_auxtrans_class_factory(axes_class=None):
    if axes_class is None:
        cbook.warn_deprecated(
            "3.3", message="Support for passing None to "
            "parasite_axes_auxtrans_class_factory is deprecated since "
            "%(since)s and will be removed %(removal)s; explicitly pass the "
            "default ParasiteAxes class instead.")
        parasite_axes_class = ParasiteAxes
    elif not issubclass(axes_class, ParasiteAxesBase):
        parasite_axes_class = parasite_axes_class_factory(axes_class)
    else:
        parasite_axes_class = axes_class
    return type("%sParasiteAuxTrans" % parasite_axes_class.__name__,
                (ParasiteAxesAuxTransBase, parasite_axes_class),
                {'name': 'parasite_axes'})


ParasiteAxesAuxTrans = parasite_axes_auxtrans_class_factory(ParasiteAxes)


class HostAxesBase:
    def __init__(self, *args, **kwargs):
        self.parasites = []
        super().__init__(*args, **kwargs)

    def get_aux_axes(self, tr, viewlim_mode="equal", axes_class=ParasiteAxes):
        parasite_axes_class = parasite_axes_auxtrans_class_factory(axes_class)
        ax2 = parasite_axes_class(self, tr, viewlim_mode)
        # note that ax2.transData == tr + ax1.transData
        # Anything you draw in ax2 will match the ticks and grids of ax1.
        self.parasites.append(ax2)
        ax2._remove_method = self.parasites.remove
        return ax2

    def _get_legend_handles(self, legend_handler_map=None):
        all_handles = super()._get_legend_handles()
        for ax in self.parasites:
            all_handles.extend(ax._get_legend_handles(legend_handler_map))
        return all_handles

    def draw(self, renderer):

        orig_artists = list(self.artists)
        orig_images = list(self.images)

        if hasattr(self, "get_axes_locator"):
            locator = self.get_axes_locator()
            if locator:
                pos = locator(self, renderer)
                self.set_position(pos, which="active")
                self.apply_aspect(pos)
            else:
                self.apply_aspect()
        else:
            self.apply_aspect()

        rect = self.get_position()

        for ax in self.parasites:
            ax.apply_aspect(rect)
            images, artists = ax.get_images_artists()
            self.images.extend(images)
            self.artists.extend(artists)

        super().draw(renderer)
        self.artists = orig_artists
        self.images = orig_images

    def cla(self):
        for ax in self.parasites:
            ax.cla()
        super().cla()

    def pick(self, mouseevent):
        super().pick(mouseevent)
        # Also pass pick events on to parasite axes and, in turn, their
        # children (cf. ParasiteAxesBase.pick)
        for a in self.parasites:
            a.pick(mouseevent)

    def twinx(self, axes_class=None):
        """
        Create a twin of Axes with a shared x-axis but independent y-axis.

        The y-axis of self will have ticks on the left and the returned axes
        will have ticks on the right.
        """
        if axes_class is None:
            axes_class = self._get_base_axes()

        parasite_axes_class = parasite_axes_class_factory(axes_class)

        ax2 = parasite_axes_class(self, sharex=self)
        self.parasites.append(ax2)
        ax2._remove_method = self._remove_any_twin

        self.axis["right"].set_visible(False)

        ax2.axis["right"].set_visible(True)
        ax2.axis["left", "top", "bottom"].set_visible(False)

        return ax2

    def twiny(self, axes_class=None):
        """
        Create a twin of Axes with a shared y-axis but independent x-axis.

        The x-axis of self will have ticks on the bottom and the returned axes
        will have ticks on the top.
        """
        if axes_class is None:
            axes_class = self._get_base_axes()

        parasite_axes_class = parasite_axes_class_factory(axes_class)

        ax2 = parasite_axes_class(self, sharey=self)
        self.parasites.append(ax2)
        ax2._remove_method = self._remove_any_twin

        self.axis["top"].set_visible(False)

        ax2.axis["top"].set_visible(True)
        ax2.axis["left", "right", "bottom"].set_visible(False)

        return ax2

    def twin(self, aux_trans=None, axes_class=None):
        """
        Create a twin of Axes with no shared axis.

        While self will have ticks on the left and bottom axis, the returned
        axes will have ticks on the top and right axis.
        """
        if axes_class is None:
            axes_class = self._get_base_axes()

        parasite_axes_auxtrans_class = \
            parasite_axes_auxtrans_class_factory(axes_class)

        if aux_trans is None:
            aux_trans = mtransforms.IdentityTransform()
        ax2 = parasite_axes_auxtrans_class(
            self, aux_trans, viewlim_mode="transform")
        self.parasites.append(ax2)
        ax2._remove_method = self._remove_any_twin

        self.axis["top", "right"].set_visible(False)

        ax2.axis["top", "right"].set_visible(True)
        ax2.axis["left", "bottom"].set_visible(False)

        return ax2

    def _remove_any_twin(self, ax):
        self.parasites.remove(ax)
        restore = ["top", "right"]
        if ax._sharex:
            restore.remove("top")
        if ax._sharey:
            restore.remove("right")
        self.axis[tuple(restore)].set_visible(True)
        self.axis[tuple(restore)].toggle(ticklabels=False, label=False)

    def get_tightbbox(self, renderer, call_axes_locator=True,
                      bbox_extra_artists=None):
        bbs = [
            *[ax.get_tightbbox(renderer, call_axes_locator=call_axes_locator)
              for ax in self.parasites],
            super().get_tightbbox(renderer,
                                  call_axes_locator=call_axes_locator,
                                  bbox_extra_artists=bbox_extra_artists)]
        return Bbox.union([b for b in bbs if b.width != 0 or b.height != 0])


@functools.lru_cache(None)
def host_axes_class_factory(axes_class=None):
    if axes_class is None:
        cbook.warn_deprecated(
            "3.3", message="Support for passing None to host_axes_class is "
            "deprecated since %(since)s and will be removed %(removed)s; "
            "explicitly pass the default Axes class instead.")
        axes_class = Axes

    def _get_base_axes(self):
        return axes_class

    return type("%sHostAxes" % axes_class.__name__,
                (HostAxesBase, axes_class),
                {'_get_base_axes': _get_base_axes})


def host_subplot_class_factory(axes_class):
    host_axes_class = host_axes_class_factory(axes_class)
    subplot_host_class = subplot_class_factory(host_axes_class)
    return subplot_host_class


HostAxes = host_axes_class_factory(Axes)
SubplotHost = subplot_class_factory(HostAxes)


def host_axes(*args, axes_class=Axes, figure=None, **kwargs):
    """
    Create axes that can act as a hosts to parasitic axes.

    Parameters
    ----------
    figure : `matplotlib.figure.Figure`
        Figure to which the axes will be added. Defaults to the current figure
        `.pyplot.gcf()`.

    *args, **kwargs
        Will be passed on to the underlying ``Axes`` object creation.
    """
    import matplotlib.pyplot as plt
    host_axes_class = host_axes_class_factory(axes_class)
    if figure is None:
        figure = plt.gcf()
    ax = host_axes_class(figure, *args, **kwargs)
    figure.add_axes(ax)
    plt.draw_if_interactive()
    return ax


def host_subplot(*args, axes_class=Axes, figure=None, **kwargs):
    """
    Create a subplot that can act as a host to parasitic axes.

    Parameters
    ----------
    figure : `matplotlib.figure.Figure`
        Figure to which the subplot will be added. Defaults to the current
        figure `.pyplot.gcf()`.

    *args, **kwargs
        Will be passed on to the underlying ``Axes`` object creation.
    """
    import matplotlib.pyplot as plt
    host_subplot_class = host_subplot_class_factory(axes_class)
    if figure is None:
        figure = plt.gcf()
    ax = host_subplot_class(figure, *args, **kwargs)
    figure.add_subplot(ax)
    plt.draw_if_interactive()
    return ax
