# -*- coding: utf-8 -*-
#
# Copyright (C) 2005-2009 Edgewall Software
# Copyright (C) 2005-2006 Christopher Lenz <cmlenz@gmx.de>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://trac.edgewall.org/wiki/TracLicense.
#
# This software consists of voluntary contributions made by many
# individuals. For the exact contribution history, see the revision
# history and logs, available at http://trac.edgewall.org/log/.
#
# Author: Christopher Lenz <cmlenz@gmx.de>

from itertools import groupby
import inspect
import os
import re
from StringIO import StringIO

from genshi.builder import Element, tag
from genshi.core import Markup

from trac.core import *
from trac.resource import Resource, ResourceNotFound, get_resource_name, \
                          get_resource_summary, get_resource_url
from trac.util.compat import any, rpartition
from trac.util.datefmt import format_date, from_utimestamp
from trac.util.html import escape
from trac.util.presentation import separated
from trac.util.text import unquote, to_unicode
from trac.util.translation import _
from trac.wiki.api import IWikiMacroProvider, WikiSystem, parse_args
from trac.wiki.formatter import format_to_html, format_to_oneliner, \
                                extract_link, OutlineFormatter


class WikiMacroBase(Component):
    """Abstract base class for wiki macros."""

    implements(IWikiMacroProvider)
    abstract = True

    def get_macros(self):
        """Yield the name of the macro based on the class name."""
        name = self.__class__.__name__
        if name.endswith('Macro'):
            name = name[:-5]
        yield name

    def get_macro_description(self, name):
        """Return the subclass's docstring."""
        doc = inspect.getdoc(self.__class__)
        return doc and to_unicode(doc) or ''

    def parse_macro(self, parser, name, content):
        raise NotImplementedError

    def expand_macro(self, formatter, name, content):
        # -- TODO: remove in 0.12
        if hasattr(self, 'render_macro'):
            self.log.warning('Executing pre-0.11 Wiki macro %s by provider %s'
                             % (name, self.__class__))            
            return self.render_macro(formatter.req, name, content)
        # -- 
        raise NotImplementedError


class TitleIndexMacro(WikiMacroBase):
    """すべての Wiki ページをアルファベットのリスト形式で出力に挿入します。

    引数として、接頭辞となる文字列を許容します: 指定された場合、
    生成されるリストにはページ名が接頭辞で始まるものだけが含まれます。
    すべてのページがリストされます。
    接頭辞が与えられた上で、第二引数に 'hideprefix' が与えられた場合、
    出力からは接頭辞が除外されます。

    この他、 `format` および `depth` などを名前付き引数として指定できます:
     - `format=compact`: ページ名をカンマ区切りのリストとして表示します。
     - `format=group`: 共通の接頭辞を持つページでリストを生成します。
       また `min=n` の引数を使用することができ、
       `n` にはリストを生成するページの最小数を指定します。
     - `format=hierarchy`: ページ名をパスとした階層構造で表示します。
       このフォーマットでも `min=n` の引数を使用することができ、
       `n` には階層を生成するページの最小数を指定します。
     - `depth=n`: リストするページの階層数を指定します。
       0を指定した場合、トップレベルのページのみ表示され、
       1を指定した場合、1代目の子ページが表示されます。
       何も指定しない場合か、-1を指定した場合、
       全てのページが階層構造により表示されます。
    """

    SPLIT_RE = re.compile(r"([/ 0-9.]+)")

    def expand_macro(self, formatter, name, content):
        args, kw = parse_args(content)
        prefix = args and args[0].strip() or None
        hideprefix = args and len(args) > 1 and args[1].strip() == 'hideprefix'
        minsize = max(int(kw.get('min', 2)), 2)
        depth = int(kw.get('depth', -1))
        start = prefix and prefix.count('/') or 0
        format = kw.get('format', '')

        if hideprefix:
            omitprefix = lambda page: page[len(prefix):]
        else:
            omitprefix = lambda page: page

        wiki = formatter.wiki

        pages = sorted(page for page in wiki.get_pages(prefix) \
                       if (depth < 0 or depth >= page.count('/') - start)
                       and 'WIKI_VIEW' in formatter.perm('wiki', page))

        if format == 'compact':
            return tag(
                separated((tag.a(wiki.format_page_name(omitprefix(p)),
                                 href=formatter.href.wiki(p)) for p in pages),
                          ', '))

        # the function definitions for the different format styles

        # the different page split formats, each corresponding to its rendering
        def split_pages_group(pages):
            """Return a list of (path elements, page_name) pairs,
            where path elements correspond to the page name (without prefix)
            splitted at Camel Case word boundaries, numbers and '/'.
            """
            page_paths = []
            for page in pages:
                path = [elt.rstrip('/').strip() for elt in self.SPLIT_RE.split(
                        wiki.format_page_name(omitprefix(page), split=True))]
                page_paths.append(([elt for elt in path if elt], page))
            return page_paths

        def split_pages_hierarchy(pages):
            """Return a list of (path elements, page_name) pairs,
            where path elements correspond to the page name (without prefix)
            splitted according to the '/' hierarchy.
            """
            return [(wiki.format_page_name(omitprefix(page)).split("/"), page)
                    for page in pages]

        # create the group hierarchy (same for group and hierarchy formats)
        def split_in_groups(entries):
            """Transform a flat list of entries into a tree structure.
            
            `entries` is a list of `(path_elements, page_name)` pairs
            
            Return a list organized in a tree structure, in which:
              - a leaf is a page name
              - a node is a `(key, nodes)` pairs, where:
                - `key` is the leftmost of the path elements, common to the
                  grouped (path element, page_name) entries
                - `nodes` is a list of nodes or leaves
            """
            groups = []

            for key, grouper in groupby(entries, lambda (elts, name):
                                                elts and elts[0] or ''):
                # remove key from path_elements in grouped entries for further
                # grouping
                grouped_entries = [(path_elements[1:], page_name)
                                   for path_elements, page_name in grouper]
                if key and len(grouped_entries) >= minsize:
                    subnodes = split_in_groups(sorted(grouped_entries))
                    if len(subnodes) == 1:
                        subkey, subnodes = subnodes[0]
                        node = (key + subkey, subnodes) # FIXME
                    else:
                        node = (key, subnodes)
                    groups.append(node)
                else:
                    for path_elements, page_name in grouped_entries:
                        groups.append(page_name)
            return groups

        # the different rendering formats
        def render_group(group):
            return tag.ul(
                tag.li(isinstance(elt, tuple) and 
                       tag(tag.strong(elt[0]), render_group(elt[1])) or
                       tag.a(wiki.format_page_name(elt),
                             href=formatter.href.wiki(elt)))
                for elt in group)

        def render_hierarchy(group):
            return tag.ul(
                tag.li(isinstance(elt, tuple) and 
                       tag(tag.a(elt[0], href=formatter.href.wiki(elt[0])),
                           render_hierarchy(elt[1][0:])) or
                       tag.a(rpartition(elt, '/')[2],
                             href=formatter.href.wiki(elt)))
                for elt in group)
        
        splitter, renderer = {
            'group':     (split_pages_group,     render_group),
            'hierarchy': (split_pages_hierarchy, render_hierarchy),
            }.get(format, (None, None))

        if splitter and renderer:
            titleindex = renderer(split_in_groups(splitter(pages)))
        else:
            titleindex = tag.ul(
                tag.li(tag.a(wiki.format_page_name(omitprefix(page)),
                             href=formatter.href.wiki(page)))
                for page in pages)

        return tag.div(titleindex, class_='titleindex')


class RecentChangesMacro(WikiMacroBase):
    """最近更新されたすべてのページを最後に変更した日付でグループ化し、リストします。

    このマクロは、 2 つの引数をとります。最初の引数はプレフィックスの文字列です:
    プレフィックスが指定された場合、結果のリストにはそのプレフィックスで始まるページのみが
    含まれます。この引数が省略された場合は、すべてのページがリストされます。

    2番目の引数は結果リストに表示するページの数を制限するために使用します。
    例えば 5 に制限すると指定した場合、最近更新されたページのうち、新しいもの
    5 件がリストに含まれます。
    """

    def expand_macro(self, formatter, name, content):
        prefix = limit = None
        if content:
            argv = [arg.strip() for arg in content.split(',')]
            if len(argv) > 0:
                prefix = argv[0]
                if len(argv) > 1:
                    limit = int(argv[1])

        cursor = formatter.db.cursor()

        sql = 'SELECT name, ' \
              '  max(version) AS max_version, ' \
              '  max(time) AS max_time ' \
              'FROM wiki'
        args = []
        if prefix:
            sql += ' WHERE name LIKE %s'
            args.append(prefix + '%')
        sql += ' GROUP BY name ORDER BY max_time DESC'
        if limit:
            sql += ' LIMIT %s'
            args.append(limit)
        cursor.execute(sql, args)

        entries_per_date = []
        prevdate = None
        for name, version, ts in cursor:
            if not 'WIKI_VIEW' in formatter.perm('wiki', name, version):
                continue
            date = format_date(from_utimestamp(ts))
            if date != prevdate:
                prevdate = date
                entries_per_date.append((date, []))
            version = int(version)
            diff_href = None
            if version > 1:
                diff_href = formatter.href.wiki(name, action='diff',
                                                version=version)
            page_name = formatter.wiki.format_page_name(name)
            entries_per_date[-1][1].append((page_name, name, version,
                                            diff_href))
        return tag.div(
            (tag.h3(date),
             tag.ul(
                 tag.li(tag.a(page, href=formatter.href.wiki(name)), ' ',
                        diff_href and
                        tag.small('(', tag.a('diff', href=diff_href), ')') or
                        None)
                 for page, name, version, diff_href in entries))
            for date, entries in entries_per_date)


class PageOutlineMacro(WikiMacroBase):
    """現在の Wiki ページの構造的なアウトラインを表示します。
    アウトラインのそれぞれの項目は一致する表題へのリンクとなります。

    このマクロは 3 つの任意のパラメータをとります:
    
     * 1 番目の引数はアウトラインに含まれる表題の範囲 (レベル) を設定することができ、
       数または数の範囲をとります。
       例えば、 "1" と指定した場合、アウトラインにはトップレベルの表題のみが表示されます。
       "2-3" と指定した場合、アウトラインには、レベル 2 とレベル 3 のすべての表題が
       ネストしたリストとして表示されます。
       デフォルトでは、すべてのレベルの表題が表示されます。
     * 2 番目の引数は、タイトルを特定するのに使われます。
       (デフォルトはタイトルなし)
     * 3 番目の引数はアウトラインのスタイルを指定します。
       inline または pullout を指定することができます (後者がデフォルトです) 。
       inline スタイルでは、アウトラインをコンテンツの一部として整形しますが、
       pullout スタイルでは、アウトラインをフローティングボックスに整形し、
       コンテンツの右側に配置します。
    """

    def expand_macro(self, formatter, name, content):
        min_depth, max_depth = 1, 6
        title = None
        inline = 0
        if content:
            argv = [arg.strip() for arg in content.split(',')]
            if len(argv) > 0:
                depth = argv[0]
                if '-' in depth:
                    min_depth, max_depth = [int(d)
                                            for d in depth.split('-', 1)]
                else:
                    min_depth = max_depth = int(depth)
                if len(argv) > 1:
                    title = argv[1].strip()
                    if len(argv) > 2:
                        inline = argv[2].strip().lower() == 'inline'

        # TODO: - integrate the rest of the OutlineFormatter directly here
        #       - use formatter.wikidom instead of formatter.source
        out = StringIO()
        OutlineFormatter(self.env, formatter.context).format(formatter.source,
                                                             out, max_depth,
                                                             min_depth)
        outline = Markup(out.getvalue())

        if title:
            outline = tag.h4(title) + outline
        if not inline:
            outline = tag.div(outline, class_='wiki-toc')
        return outline


class ImageMacro(WikiMacroBase):
    """画像を Wiki 形式のテキストに組み込みます。
    
    1 番目の引数は、ファイル名を指定します。ファイルの指定は添付ファイルなど
    3つの指定方法があります:
     * `module:id:file`: module に '''wiki''' または '''ticket''' が指定すると、
       その Wiki ページまたはチケットの添付ファイルで ''file'' とファイル名が
       ついているものを参照します。
     * `id:file`: 上記と同様ですが、 id はチケットの短い記述方法か、 Wiki
       ページ名を指定します。
     * `file`: 'file' というローカルの添付ファイルを指します。これはファイルが
       添付されている Wiki ページまたはチケットの中でのみ使用できます。
    
    またファイルはリポジトリのファイルも指定できます。
    `source:file` シンタックスを使用します。 (`source:file@rev` も可能です)
    
    直接 URL を記述することもできます; `/file` と記述すると、プロジェクトの
    ディレクトリからの相対パスになり、 `//file` と記述すると、サーバルートからの
    パスになります。また、 `http://server/file` ではファイルの絶対パスになります。
    
    残りの引数は任意で、
    `<img>` 要素を組み立てる際の属性を設定します:
     * 数字と単位は画像のサイズと解釈されます。
       (ex. 120, 25%)
     * `right`, `left`, `center`, `top`, `bottom`, `middle` は画像の配置として
       解釈されます。 (`right`, `left`, `center` は `align=...` でも指定でき、
       `top`, `bottom`, `middle` は `valign=...` でも指定できます)
     * `link=some TracLinks...` を指定すると、画像のソースへのリンクが、
       TracLinks に置き換えられます。値なしで引数が指定された場合、
       リンクは単に削除されます。
     * `nolink` は画像のソースへのリンクを作成しません。 (非推奨, `link=` を使用してください)
     * `key=value` スタイルは画像の HTML 属性または CSS スタイルの
        指示として解釈されます。有効なキーは以下の通りです:
        * align, valign, border, width, height, alt, title, longdesc, class,
          margin, margin-(left,right,top,bottom), id, usemap
        * `border`, `margin`, `margin-*` は数値での指定のみ可能です。
        * `margin` は `center` によって自動計算されたマージンを上書きします。
    
    例:
    {{{
        [[Image(photo.jpg)]]                           # シンプルな指定方法
        [[Image(photo.jpg, 120px)]]                    # 画像の幅サイズ指定
        [[Image(photo.jpg, right)]]                    # キーワードによる配置指定
        [[Image(photo.jpg, nolink)]]                   # ソースへのリンクなし
        [[Image(photo.jpg, align=right)]]              # 属性による配置指定
    }}}

    他の wiki ページ、チケット、モジュールの画像を使用することができます。
    {{{
        [[Image(OtherPage:foo.bmp)]]    # 現在のモジュールが Wiki の場合
        [[Image(base/sub:bar.bmp)]]     # 下位の Wiki ページから
        [[Image(#3:baz.bmp)]]           # #3というチケットを指している場合
        [[Image(ticket:36:boo.jpg)]]
        [[Image(source:/images/bee.jpg)]] # リポジトリから直接指定する！
        [[Image(htdocs:foo/bar.png)]]   # プロジェクトの htdocs ディレクトリにあるファイル
    }}}

    ''このマクロは Shun-ichi Goto <gotoh@taiyo.co.jp> さんが作成した Image.py が
    元になっています''
    """

    def expand_macro(self, formatter, name, content):
        # args will be null if the macro is called without parenthesis.
        if not content:
            return ''
        # parse arguments
        # we expect the 1st argument to be a filename (filespec)
        args = content.split(',')
        if len(args) == 0:
            raise Exception("No argument.")
        filespec = args.pop(0)

        # style information
        size_re = re.compile('[0-9]+(%|px)?$')
        attr_re = re.compile('(align|valign|border|width|height|alt'
                             '|margin(?:-(?:left|right|top|bottom))?'
                             '|title|longdesc|class|id|usemap)=(.+)')
        quoted_re = re.compile("(?:[\"'])(.*)(?:[\"'])$")
        attr = {}
        style = {}
        link = ''
        while args:
            arg = args.pop(0).strip()
            if size_re.match(arg):
                # 'width' keyword
                attr['width'] = arg
            elif arg == 'nolink':
                link = None
            elif arg.startswith('link='):
                val = arg.split('=', 1)[1]
                elt = extract_link(self.env, formatter.context, val.strip())
                link = None
                if isinstance(elt, Element):
                    link = elt.attrib.get('href')
            elif arg in ('left', 'right'):
                style['float'] = arg
            elif arg == 'center':
                style['margin-left'] = style['margin-right'] = 'auto'
                style['display'] = 'block'
                style.pop('margin', '')
            elif arg in ('top', 'bottom', 'middle'):
                style['vertical-align'] = arg
            else:
                match = attr_re.match(arg)
                if match:
                    key, val = match.groups()
                    if (key == 'align' and 
                            val in ('left', 'right', 'center')) or \
                        (key == 'valign' and \
                            val in ('top', 'middle', 'bottom')):
                        args.append(val)
                    elif key in ('margin-top', 'margin-bottom'):
                        style[key] = ' %dpx' % int(val)
                    elif key in ('margin', 'margin-left', 'margin-right') \
                             and 'display' not in style:
                        style[key] = ' %dpx' % int(val)
                    elif key == 'border':
                        style['border'] = ' %dpx solid' % int(val)
                    else:
                        m = quoted_re.search(val) # unquote "..." and '...'
                        if m:
                            val = m.group(1)
                        attr[str(key)] = val # will be used as a __call__ kwd

        # parse filespec argument to get realm and id if contained.
        parts = filespec.split(':')
        url = raw_url = desc = None
        attachment = None
        if (parts and parts[0] in ('http', 'https', 'ftp')): # absolute
            raw_url = url = desc = filespec
        elif filespec.startswith('//'):       # server-relative
            raw_url = url = desc = filespec[1:]
        elif filespec.startswith('/'):        # project-relative
            # use href, but unquote to allow args (use default html escaping)
            raw_url = url = desc = unquote(formatter.href(filespec))
        elif len(parts) == 3:                 # realm:id:attachment-filename
            realm, id, filename = parts
            attachment = Resource(realm, id).child('attachment', filename)
        elif len(parts) == 2:
            # FIXME: somehow use ResourceSystem.get_known_realms()
            #        ... or directly trac.wiki.extract_link
            from trac.versioncontrol.web_ui import BrowserModule
            try:
                browser_links = [res[0] for res in
                                 BrowserModule(self.env).get_link_resolvers()]
            except Exception:
                browser_links = []
            if parts[0] in browser_links:   # source:path
                # TODO: use context here as well
                realm, filename = parts
                rev = None
                if '@' in filename:
                    filename, rev = filename.split('@')
                url = formatter.href.browser(filename, rev=rev)
                raw_url = formatter.href.browser(filename, rev=rev,
                                                 format='raw')
                desc = filespec
            else: # #ticket:attachment or WikiPage:attachment
                # FIXME: do something generic about shorthand forms...
                realm = None
                id, filename = parts
                if id and id[0] == '#':
                    realm = 'ticket'
                    id = id[1:]
                elif id == 'htdocs':
                    raw_url = url = formatter.href.chrome('site', filename)
                    desc = os.path.basename(filename)
                else:
                    realm = 'wiki'
                if realm:
                    attachment = Resource(realm, id).child('attachment',
                                                           filename)
        elif len(parts) == 1: # it's an attachment of the current resource
            attachment = formatter.resource.child('attachment', filespec)
        else:
            raise TracError('No filespec given')
        if attachment and 'ATTACHMENT_VIEW' in formatter.perm(attachment):
            url = get_resource_url(self.env, attachment, formatter.href)
            raw_url = get_resource_url(self.env, attachment, formatter.href,
                                       format='raw')
            try:
                desc = get_resource_summary(self.env, attachment)
            except ResourceNotFound, e:
                raw_url = formatter.href.chrome('common/attachment.png')
                desc = _('No image "%(id)s" attached to %(parent)s',
                         id=attachment.id,
                         parent=get_resource_name(self.env, attachment.parent))
        for key in ('title', 'alt'):
            if desc and not key in attr:
                attr[key] = desc
        if style:
            attr['style'] = '; '.join('%s:%s' % (k, escape(v))
                                      for k, v in style.iteritems())
        result = tag.img(src=raw_url, **attr)
        if link is not None:
            result = tag.a(result, href=link or url,
                           style='padding:0; border:none')
        return result


class MacroListMacro(WikiMacroBase):
    """インストールされている、すべての Wiki マクロをリストします。
    もし利用可能ならばドキュメントも含みます。
    
    非必須オプションとして、特定のマクロの名前を引数として渡すことが出来ます。
    この場合、指定されたマクロのドキュメントだけを表示します。
    
    Note: このマクロは mod_python の `PythonOptimize` オプションが有効になっている
    場合は、マクロのドキュメントを表示することが出来ません!
    """

    def expand_macro(self, formatter, name, content):
        from trac.wiki.formatter import system_message

        content = content and content.strip() or ''
        name_filter = content.strip('*')

        def get_macro_descr():
            for macro_provider in formatter.wiki.macro_providers:
                names = list(macro_provider.get_macros() or [])
                if name_filter and not any(name.startswith(name_filter)
                                           for name in names):
                    continue
                try:
                    name_descriptions = [
                        (name, macro_provider.get_macro_description(name))
                        for name in names]
                except Exception, e:
                    yield system_message(
                        _("Error: Can't get description for macro %(name)s",
                          name=names[0]), e), names
                else:
                    for descr, pairs in groupby(name_descriptions,
                                                key=lambda p: p[1]):
                        if descr:
                            descr = to_unicode(descr) or ''
                            if content == '*':
                                descr = format_to_oneliner(
                                    self.env, formatter.context, descr,
                                    shorten=True)
                            else:
                                descr = format_to_html(
                                    self.env, formatter.context, descr)
                        yield descr, [name for name, descr in pairs]

        return tag.div(class_='trac-macrolist')(
            (tag.h3(tag.code('[[', names[0], ']]'), id='%s-macro' % names[0]),
             len(names) > 1 and tag.p(tag.strong(_("Aliases:")),
                                      [tag.code(' [[', alias, ']]')
                                       for alias in names[1:]]) or None,
             description or tag.em(_("Sorry, no documentation found")))
            for description, names in list(get_macro_descr()))


class TracIniMacro(WikiMacroBase):
    """Trac の設定ファイルのドキュメントを生成します。

    通常、このマクロは Wiki ページ TracIni の中で使用されます。
    省略可能な引数にはコンフィグのセクションのフィルタ、
    コンフィグのオプション名のフィルタを指定できます: フィルタで指定された文字列
    で始まるコンフィグのセクションとオプション名のみが出力されます。
    """

    def expand_macro(self, formatter, name, args):
        from trac.config import Option
        section_filter = key_filter = ''
        args, kw = parse_args(args)
        if args:
            section_filter = args.pop(0).strip()
        if args:
            key_filter = args.pop(0).strip()

        registry = Option.get_registry(self.compmgr)
        sections = {}
        for (section, key), option in registry.iteritems():
            if section.startswith(section_filter):
                sections.setdefault(section, {})[key] = option

        return tag.div(class_='tracini')(
            (tag.h3(tag.code('[%s]' % section), id='%s-section' % section),
             tag.table(class_='wiki')(
                 tag.tbody(tag.tr(tag.td(tag.tt(option.name)),
                                  tag.td(format_to_oneliner(
                                      self.env, formatter.context,
                                      to_unicode(option.__doc__))))
                           for option in sorted(sections[section].itervalues(),
                                                key=lambda o: o.name)
                           if option.name.startswith(key_filter))))
            for section in sorted(sections))



class KnownMimeTypesMacro(WikiMacroBase):
    """WikiProcessors で処理できる既知の mime-type を表示します。

    引数が与えられた場合は、 mime-type へのフィルタとして作用します。
    """

    def expand_macro(self, formatter, name, args):
        from trac.mimeview.api import Mimeview
        mime_map = Mimeview(self.env).mime_map
        mime_type_filter = ''
        args, kw = parse_args(args)
        if args:
            mime_type_filter = args.pop(0).strip().rstrip('*')

        mime_types = {}
        for key, mime_type in mime_map.iteritems():
            if (not mime_type_filter or
                mime_type.startswith(mime_type_filter)) and key != mime_type:
                mime_types.setdefault(mime_type, []).append(key)

        return tag.div(class_='mimetypes')(
            tag.table(class_='wiki')(
                tag.thead(tag.tr(
                    tag.th(_("MIME Types")), # always use plural
                    tag.th(tag.a("WikiProcessors",
                                 href=formatter.context.href.wiki(
                                     'WikiProcessors'))))),
                tag.tbody(
                    tag.tr(tag.th(tag.tt(mime_type),
                                  style="text-align: left"),
                           tag.td(tag.code(
                               ' '.join(sorted(mime_types[mime_type])))))
                    for mime_type in sorted(mime_types.keys()))))



class TracGuideTocMacro(WikiMacroBase):
    """Trac ガイドの目次を表示する。
    
    このマクロは !Help/Guide の目次 (ToC) を簡単かつ荒っぽく作成します。
    この目次には Trac* と WikiFormatting のページが含まれていますが、
    カスタマイズはできません。目次をカスタマイズしたい場合は、 !TocMacro
    を探してください。
    """

    TOC = [('TracGuide',                    'Index'),
           ('TracInstall',                  'Installation'),
           ('TracInterfaceCustomization',   'Customization'),
           ('TracPlugins',                  'Plugins'),
           ('TracUpgrade',                  'Upgrading'),
           ('TracIni',                      'Configuration'),
           ('TracAdmin',                    'Administration'),
           ('TracBackup',                   'Backup'),
           ('TracLogging',                  'Logging'),
           ('TracPermissions' ,             'Permissions'),
           ('TracWiki',                     'The Wiki'),
           ('WikiFormatting',               'Wiki Formatting'),
           ('TracTimeline',                 'Timeline'),
           ('TracBrowser',                  'Repository Browser'),
           ('TracRevisionLog',              'Revision Log'),
           ('TracChangeset',                'Changesets'),
           ('TracTickets',                  'Tickets'),
           ('TracWorkflow',                 'Workflow'),
           ('TracRoadmap',                  'Roadmap'),
           ('TracQuery',                    'Ticket Queries'),
           ('TracReports',                  'Reports'),
           ('TracRss',                      'RSS Support'),
           ('TracNotification',             'Notification'),
          ]

    def expand_macro(self, formatter, name, args):
        curpage = formatter.resource.id

        # scoped TOC (e.g. TranslateRu/TracGuide or 0.11/TracGuide ...)
        prefix = ''
        idx = curpage.find('/')
        if idx > 0:
            prefix = curpage[:idx+1]
            
        ws = WikiSystem(self.env)
        return tag.div(
            tag.h4(_('Table of Contents')),
            tag.ul([tag.li(tag.a(title, href=formatter.href.wiki(prefix+ref),
                                 class_=(not ws.has_page(prefix+ref) and
                                         'missing')),
                           class_=(prefix+ref == curpage and 'active'))
                    for ref, title in self.TOC]),
            class_='wiki-toc')
