from django import template
from django.core.cache import cache
from django.utils.safestring import SafeUnicode

from cms import settings
from cms.models import Page, Title, PagePermission, CMSPlugin
from cms.utils import get_language_from_request, get_page_from_request

register = template.Library()

def get_page_children_for_site(page, site, levels=100):
    if page:
        pages = Page.objects.published().filter(in_navigation=True, 
                                                lft__gt=page.lft, 
                                                rght__lt=page.rght, 
                                                tree_id=page.tree_id, 
                                                level__lte=page.level+levels, 
                                                sites__domain=site)
        return pages
    else:
        return []
    
def find_children(target, pages, levels=100, active_levels=0, ancestors=None, selected_pk=0, soft_roots=True):
    if not hasattr(target, "childrens"):
        target.childrens = []
    if ancestors == None:
        ancestors = []
    if target.pk in ancestors:
        target.ancestor = True
    if target.pk == selected_pk:
        target.selected = True
        levels = active_levels
    if (levels <= 0 or (target.soft_root and soft_roots)) and not target.pk in ancestors:
        return 
    
    for page in pages:
        if page.parent_id and page.parent_id == target.pk:
            if hasattr(target, "selected") or hasattr(target, "descendant"):
                page.descendant = True
            if len(target.childrens):
                target.childrens[-1].last = False
            page.last = True
            target.childrens.append(page)    
            find_children(page, pages, levels-1, active_levels, ancestors, selected_pk, soft_roots)
            
                
    

def show_menu(context, from_level=0, to_level=100, extra_inactive=0, extra_active=100, next_page=None):
    """
    render a nested list of all children of the pages
    from_level: is the start level
    to_level: is the max level rendered
    render_children: if set to True will render all not direct ascendants too
    """
    request = context['request']
    site = request.site
    CMS_CONTENT_CACHE_DURATION = settings.CMS_CONTENT_CACHE_DURATION
    lang = get_language_from_request(request)
    if 'current_page' in context:
        current_page = get_page_from_request(context)# TODO: change to request
        if not next_page and current_page: #new menu... get all the data so we can save a lot of queries
            ids = []
            children = []
            ancestors = []
            alist = current_page.get_ancestors().values_list('id', 'soft_root')
            soft_root_filter = {}
            #check the ancestors for softroots
            for p in alist:
                ancestors.append(p[0])
                if p[1]:
                    soft_root = Page.objects.get(pk=p[0])
                    soft_root_filter['lft__gte'] = soft_root.lft
                    soft_root_filter['rght__lte'] = soft_root.rght
                    soft_root_filter['tree_id'] = soft_root.tree_id
                    from_level = soft_root.level
            if current_page.soft_root:
                soft_root_filter['tree_id'] = current_page.tree_id
                soft_root_filter['lft__gte'] = current_page.lft
                soft_root_filter['rght__lte'] = current_page.rght
                #current_page.soft_root = False
                from_level = current_page.level
            pages = list(Page.objects.published().filter(in_navigation=True, sites__domain=site).order_by('tree_id', 'parent', 'lft').filter(level__gte=from_level, level__lte=to_level, **soft_root_filter))
            all_pages = pages[:]
            for page in pages:# build the tree
                ids.append(page.pk)
                if page.level == from_level:
                    children.append(page)
                    if page.pk == current_page.pk and current_page.soft_root:
                        page.soft_root = False #ugly hack for the recursive function
                    find_children(page, pages, extra_inactive, extra_active, ancestors, current_page.pk)
                    if page.pk == current_page.pk and current_page.soft_root:
                        page.soft_root = True
            titles = Title.objects.filter(pk__in=ids, language=lang)
            for page in all_pages:# add the title and slugs and some meta data
                for title in titles:
                    if title.page_id == page.pk:
                        page.title_cache = title
                if page.pk in ancestors:
                    page.ancestor = True
                if page.parent_id == current_page.parent_id and not page.pk == current_page.pk:
                    page.sibling = True
                
        else:
            if current_page and next_page.childrens:
                children = next_page.childrens
            else:
                children = []
    return locals()
show_menu = register.inclusion_tag('cms/menu.html', takes_context=True)(show_menu)

def show_sub_menu(context, levels=100):
    """Get the root page of the current page and 
    render a nested list of all root's children pages"""
    page = get_page_from_request(context)# TODO: change to request
    root = page.get_root()
    request = context['request']
    lang = get_language_from_request(request)
    site = request.site
    pages = get_page_children_for_site(page, site, levels)
    ids = []
    children = []
    all_pages = pages[:]
    for p in pages:# build the tree
        ids.append(p.pk)
        if p.parent_id == page.pk:
            children.append(p)
            find_children(p, pages, levels, levels, [], -1)
    titles = Title.objects.filter(pk__in=ids, language=lang)
    for p in all_pages:# add the title and slugs and some meta data
        for title in titles:
            if title.page_id == p.pk:
                p.title_cache = title
    from_level = page.level
    to_level = page.level+levels
    extra_active = extra_inactive = levels
    return locals()
show_sub_menu = register.inclusion_tag('cms/sub_menu.html',
                                       takes_context=True)(show_sub_menu)

                                            
def show_admin_menu(context, page, no_children=False, level=None):
    """Render the admin table of pages"""
    request = context['request']
    site = request.site
    lang = get_language_from_request(request)
    if hasattr(page, "childrens"):
        children = page.childrens
    else:
        children = []
        if not no_children:
            pages = Page.objects.filter(tree_id=page.tree_id, level__gt=page.level).order_by('tree_id', 'parent', 'lft')
            if settings.CMS_PERMISSION:
                perm_edit_ids = PagePermission.objects.get_edit_id_list(request.user)
                perm_publish_ids = PagePermission.objects.get_publish_id_list(request.user)
                perm_softroot_ids = PagePermission.objects.get_softroot_id_list(request.user)
                if perm_edit_ids and perm_edit_ids != "All":
                    pages = pages.filter(pk__in=perm_edit_ids)
            ids = []
            all_pages = pages[:]
            has_childrens = False
            for p in pages:# build the tree
                ids.append(p.pk)
                if settings.CMS_PERMISSION:# caching the permissions
                    if perm_edit_ids == "All" or p.pk in perm_edit_ids:
                        p.permission_edit_cache = True
                    else:
                        p.permission_edit_cache = False
                    if perm_publish_ids == "All" or p.pk in perm_publish_ids:
                        p.permission_publish_cache = True
                    else:
                        p.permission_publish_cache = False
                    if perm_publish_ids == "All" or p.pk in perm_softroot_ids:
                        p.permission_softroot_cache = True
                    else:
                        p.permission_softroot_cache = False
                    p.permission_user_cache = request.user
                if p.parent_id == page.pk:
                    has_childrens = True
                    p.last = True
                    if len(children):
                        children[-1].last = False
                    children.append(p)
                    find_children(p, pages, 1000, 1000, [], -1, soft_roots=False)
            if not has_childrens:
                page.childrens = []
            titles = Title.objects.filter(pk__in=ids, language=lang)
            for p in all_pages:# add the title and slugs and some meta data
                for title in titles:
                    if title.page_id == p.pk:
                        p.title_cache = title
    has_permission = page.has_page_permission(request)
    has_publish_permission = page.has_publish_permission(request)
    
    # level is used to add a left margin on table row
    if level is None:
        level = 0
    else:
        level = level+2
    return locals()
show_admin_menu = register.inclusion_tag('admin/cms/page/menu.html',
                                         takes_context=True)(show_admin_menu)

def show_breadcrumb(context, start_level=0):
    request = context['request']
    lang = get_language_from_request(request)
    page = get_page_from_request(context)# TODO: change to request
    if page:
        ancestors = list(page.get_ancestors())
        ancestors.append(page)
        ids = []
        for anc in ancestors:
            ids.append(anc.pk)
        titles = Title.objects.filter(pk__in=ids, language=lang)
        for anc in ancestors:
            for title in titles:
                if title.page_id == anc.pk:
                    anc.title_cache = title
    else:
        ancestors = []
    return locals()
show_breadcrumb = register.inclusion_tag('cms/breadcrumb.html',
                                         takes_context=True)(show_breadcrumb)

def has_permission(page, request):
    return page.has_page_permission(request)
register.filter(has_permission)

def show_content(context, content_type, lang=None):
    """Display a content type from a page.
    
    eg: {% show_content page_object "title" %}
    
    You can also use the slug of a page
    
    eg: {% show_content "my-page-slug" "title" %}
    
    Keyword arguments:
    page -- the page object
    args -- content_type used by a placeholder
    lang -- the wanted language (default None, use the request object to know)
    """
    page = get_page_from_request(context)
    request = context.get('request', False)
    if not request or not page:
        return {'content':''}
    # if the page is a SafeUnicode, try to use it like a slug
    #if isinstance(page, SafeUnicode):
    #    c = Content.objects.filter(type='slug', body=page)
    #    if len(c):
    #        page = c[0].page
    #    else:
    #        return {'content':''}
    if lang is None:
        lang = get_language_from_request(context['request'])
    if hasattr(settings, 'CMS_CONTENT_CACHE_DURATION'):
        key = 'content_cache_pid:'+str(page.id)+'_l:'+str(lang)+'_type:'+str(content_type)
        c = cache.get(key)
        if not c:
            c = Content.objects.get_content(page, lang, content_type, True)
            cache.set(key, c, settings.CMS_CONTENT_CACHE_DURATION)
    else:
        c = Content.objects.get_content(page, lang, content_type, True)
    if c:
        return {'content':c}
    return {'content':''}
show_content = register.inclusion_tag('cms/content.html',
                                      takes_context=True)(show_content)

def show_absolute_url(context, page, lang=None):
    """Show the url of a page in the right language"""
    request = context.get('request', False)
    if not request or not page:
        return {'content':''}
    if lang is None:
        lang = get_language_from_request(context['request'])
    if hasattr(settings, 'CMS_CONTENT_CACHE_DURATION'):
        key = 'page_url_pid:'+str(page.id)+'_l:'+str(lang)+'_type:absolute_url'
        url = cache.get(key)
        if not url:
            url = page.get_absolute_url(language=lang)
            cache.set(key, url, settings.CMS_CONTENT_CACHE_DURATION)
    else:
        url = page.get_absolute_url(language=lang)
    if url:
        return {'content':url}
    return {'content':''}
show_absolute_url = register.inclusion_tag('cms/content.html',
                                      takes_context=True)(show_absolute_url)

def show_revisions(context, page, content_type, lang=None):
    """Render the last 10 revisions of a page content with a list"""
    if not settings.CMS_CONTENT_REVISION:
        return {'revisions':None}
    revisions = Content.objects.filter(page=page, language=lang,
                                type=content_type).order_by('-creation_date')
    if len(revisions) < 2:
        return {'revisions':None}
    return {'revisions':revisions[0:10]}

show_revisions = register.inclusion_tag('cms/revisions.html',
                                        takes_context=True)(show_revisions)

def do_placeholder(parser, token):
    error_string = '%r tag requires three arguments' % token.contents[0]
    try:
        # split_contents() knows not to split quoted strings.
        bits = token.split_contents()
    except ValueError:
        raise template.TemplateSyntaxError(error_string)
    if len(bits) == 2:
        #tag_name, name
        return PlaceholderNode(bits[1])
    elif len(bits) == 3:
        #tag_name, name, widget
        return PlaceholderNode(bits[1], bits[2])
    else:
        raise template.TemplateSyntaxError(error_string)

class PlaceholderNode(template.Node):
    """This template node is used to output page content and
    is also used in the admin to dynamicaly generate input fields.
    
    eg: {% placeholder content-type-name page-object widget-name %}
    
    Keyword arguments:
    content-type-name -- the content type you want to show/create
    page-object -- the page object
    widget-name -- the widget name you want into the admin interface. Take
        a look into pages.admin.widgets to see which widgets are available.
    """
    def __init__(self, name, plugins=None):
        self.name = name
        if plugins:
            self.plugins = plugins
        else:
            self.plugins = []
        

    def render(self, context):
        self.page = get_page_from_request(context) #TODO: change to request
        if not 'request' in context:
            return ''
        l = get_language_from_request(context['request'])
        request = context['request']
        c = None
        if self.name.lower() == "title":
            t = Title.objects.get_title(self.page, l, True)
            if t:
                c = t.title
        elif self.name.lower() == "slug":
            t = Title.objects.get_title(self.page, l, True)
            if t:
                c = t.slug
        else:
            plugins = CMSPlugin.objects.filter(page=self.page, language=l)
            c = ""
            for plugin in plugins:
                c += plugin.plugin_type
        if not c:
            return ''
        return '<div id="%s" class="placeholder">%s</div>' % (self.name, c)
        
    def __repr__(self):
        return "<Placeholder Node: %s>" % self.name

register.tag('placeholder', do_placeholder)